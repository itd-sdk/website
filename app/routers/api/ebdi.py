from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc
from starlette.websockets import WebSocketDisconnect

from app.logger import get_logger
from app.schemas.app import App
from app.schemas.user import User
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
    created_at: datetime
    username: str
    display_name: str
    followers: list[UUID] = Field(validation_alias="followed_by_users")
    following: list[UUID] = Field(validation_alias="following_users")
    followers_count: int = Field(validation_alias="followers")
    following_count: int = Field(validation_alias="following")
    posts_count: int = Field(validation_alias="posts")
    verified: bool
    avatar: str


class UserResponse(UserBody):
    id: int
    user_id: UUID
    found_at: datetime
    has_itdp: bool

    @field_validator("followers", "following", mode="before")
    @classmethod
    def parse_uuid_list(cls, v):
        if isinstance(v, str):
            return eval(v)
        return v


class UserOrder(Enum):
    followers = "followers"
    following = "following"
    posts = "posts"
    created_at = "created_at"
    found_at = "found_at"
    updated_at = "updated_at"


@router.websocket("/users")
async def api_websocket_ebdi_users(
    websocket: WebSocket, app_token: str, db: Session = Depends(get_db)
):
    l.info("init connection")
    remove_expired_tasks()

    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        l.info("decline reason=invalid token")
        await websocket.close(1008, "invalid app token")
        return
    if app.name in [task.app.name for task in tasks]:
        l.info("decline reason=already exists")
        await websocket.close(1007, "task already exists")
        return

    await websocket.accept()
    task: Task | None = None
    try:
        users = db.query(User).order_by(User.updated_at)
        while True:
            task = Task(app, users.where(User.id.not_in(get_targets())).limit(20).all())
            l.info("create task for %s", app.name)
            if not task.targets:
                l.warning("no targets")
                await websocket.send_json({"message": "done"})
                return

            tasks.append(task)

            for user in task.targets:
                l.info("send %s to %s", user.user_id, app.name)
                await websocket.send_json({"type": "user", "id": str(user.user_id)})
                updated = UserBody.model_validate(
                    await websocket.receive_json(), by_alias=False, by_name=True
                )
                l.info("received %s from %s", updated.username, app.name)

                user.created_at = updated.created_at
                user.username = updated.username
                user.display_name = updated.display_name
                user.followed_by_users = str(updated.followers)
                user.following_users = str(updated.following)
                user.followers = updated.followers_count
                user.following = updated.following_count
                user.posts = updated.posts_count
                user.verified = updated.verified
                user.avatar = updated.avatar

            db.commit()
            tasks.remove(task)
            task = None
    except WebSocketDisconnect:
        l.info("close connection %s", app.name)
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
        followed_by_users=str(body.followers),
        following_users=str(body.following),
        followers=body.followers_count,
        following=body.following_count,
        posts=body.posts_count,
        verified=body.verified,
        avatar=body.avatar
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    app.added += 1
    return user
