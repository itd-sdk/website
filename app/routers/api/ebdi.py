from asyncio import wait_for
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import desc
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError

from app.logger import get_logger
from app.schemas import App, User
from app.services.db import Session, get_db

router = APIRouter(prefix="/ebdi")
l = get_logger("ebdi")


@dataclass
class Task:
    app: App
    targets: list[User]
    type: str = "update"
    started_at: datetime = field(default_factory=lambda: datetime.now())


tasks: list[Task] = []


def get_targets():
    targets = []
    for task in tasks:
        targets.extend([target.id for target in task.targets])
    return targets


def remove_expired_tasks():
    now = datetime.now()
    expired = [t for t in tasks if now - t.started_at > timedelta(minutes=15)]
    for t in expired:
        l.warning("expire task for %s", t.app.name)
        tasks.remove(t)


class UserBody(BaseModel):
    created_at: datetime | None = None
    username: str
    display_name: str
    followers: list[UUID]
    following: list[UUID]
    followers_count: int
    following_count: int
    posts_count: int
    verified: bool
    avatar: str
    bio: str | None = None
    banner: str | None = None


class UserResponse(UserBody):
    id: int
    user_id: UUID
    found_at: datetime
    has_itdp: bool


class WSRequestType(Enum):
    task = "task"
    update = "update"


class WSTargetType(Enum):
    user = "user"


class WSRequest(BaseModel):
    type: WSRequestType
    target_type: WSTargetType | None = None
    target: UserBody | None = None
    target_exists: bool | None = None
    target_id: UUID | None = None


class UserOrder(Enum):
    followers = "followers_count"
    following = "following_count"
    posts_count = "posts_count"
    created_at = "created_at"
    found_at = "found_at"
    updated_at = "updated_at"


@router.websocket("/")
async def api_websocket_ebdi(
    websocket: WebSocket, app_token: str, db: Session = Depends(get_db)
):
    l.info("init connection")
    remove_expired_tasks()

    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        l.info("decline reason=invalid token")
        await websocket.close(3003, "invalid app token")
        return
    if app.name in [task.app.name for task in tasks]:
        l.info("decline reason=already exists")
        await websocket.close(4000, "task already exists")
        return

    await websocket.accept()
    task: Task | None = None
    try:
        while True:
            try:
                request = WSRequest.model_validate(
                    await wait_for(websocket.receive_json(), 60)
                )
            except TimeoutError:
                l.error("(%s) timeout", app.name)
                await websocket.close(3008, "timeout")
                return

            if request.type == WSRequestType.task:
                if task is not None:
                    tasks.remove(task)

                task = Task(
                    app,
                    db.query(User)
                    .order_by(User.updated_at)
                    .where(User.id.not_in(get_targets()))
                    .limit(20)
                    .all()
                )
                l.debug("(%s) new task", app.name)
                if not task.targets:
                    l.warning("(%s) no targets", app.name)
                    await websocket.send_json({"type": "done"})
                    return

                tasks.append(task)

                await websocket.send_json(
                    {
                        "type": "task",
                        "target_type": WSTargetType.user.value,
                        "targets": [str(target.user_id) for target in task.targets]
                    }
                )

            if request.type == WSRequestType.update:
                assert request.target_type

                if task is None:
                    l.error("(%s) no task", app.name)
                    await websocket.send_json({"type": "error", "detail": "no task"})
                    continue

                if request.target_type == WSTargetType.user:
                    assert request.target_id
                    user = next(
                        (
                            user
                            for user in task.targets
                            if user.user_id == request.target_id
                        ),
                        None
                    )
                    if user is None:
                        l.error("(%s) user not in task targets", app.name)
                        await websocket.send_json(
                            {"type": "error", "detail": "user not in task targets"}
                        )
                        continue

                    if request.target_exists:
                        assert request.target
                        l.debug("(%s) < %s", app.name, request.target.username)
                        for i in request.target.model_fields_set:
                            setattr(user, i, getattr(request.target, i))
                        user.updated_at = datetime.now()

                    else:
                        l.debug("(%s) < not exists", app.name)
                        user.exists = False
                        user.updated_at = datetime.now()

                    await websocket.send_json({"type": "updated"})
                    app.refreshed += 1
                    db.commit()

    except (WebSocketDisconnect, ConnectionClosedError):
        l.warning("(%s) disconnect", app.name)
    finally:
        if task is not None:
            tasks.remove(task)


@router.get("/users", response_model=list[UserResponse])
def api_get_ebdi_users(
    offset: int = 0,
    order: UserOrder = UserOrder.followers,
    descending: bool = True,
    db: Session = Depends(get_db)
):
    col = getattr(User, order.value)
    return [
        UserResponse.model_validate(user, from_attributes=True)
        for user in db.query(User)
        .order_by(desc(col) if descending else col)
        .offset(offset)
        .limit(100)
        .all()
    ]


@router.post("/users")
def api_post_ebdi(
    app_token: str, id: UUID, body: UserBody, db: Session = Depends(get_db)
):
    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        return JSONResponse({"detail": "invalid app token"}, 401)

    if db.query(User).where(User.user_id == id).first() is not None:
        return JSONResponse({"detail": "user already exists"}, 409)

    user = User(
        user_id=id,
        created_at=body.created_at,
        username=body.username,
        display_name=body.display_name,
        followers=body.followers,
        following=body.following,
        followers_count=body.followers_count,
        following_count=body.following_count,
        posts_count=body.posts_count,
        verified=body.verified,
        avatar=body.avatar
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    app.added += 1
    return user
