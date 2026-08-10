from asyncio import wait_for
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket
from pydantic import BaseModel
from sqlalchemy import case, desc, func
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError

from app.logger import get_logger
from app.schemas import App, User
from app.services.db import Session, get_db

router = APIRouter(prefix="/websocket")
l = get_logger("ebdi.websocket")


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
    last_seen: str | None = None


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
    update_followers: bool | None = None
    update_following: bool | None = None


def refresh_interval():
    refresh_tiers = [
        (1000, timedelta(hours=12)),
        (500, timedelta(days=1)),
        (100, timedelta(days=3)),
        (10, timedelta(days=7)),
        (0, timedelta(days=14))
    ]

    base = case(
        *[
            (User.followers_count >= threshold, int(interval.total_seconds()))
            for threshold, interval in refresh_tiers
        ],
        else_=int(refresh_tiers[-1][1].total_seconds())
    )
    multiplier = case(
        *[
            (User.last_seen == value, multiplier)
            for value, multiplier in {
                "just_now": 1,
                "recently": 1,
                "minutes": 1,
                "hours": 1,
                "this_week": 2,
                "this_month": 6,
                "long_ago": 20
            }.items()
        ],
        else_=2
    )
    return func.least(
        base * multiplier * case((User.exists.is_(False), 10), else_=1),
        int(timedelta(days=30).total_seconds())
    )


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
                    task = None

                priority = (
                    func.extract("epoch", func.now() - User.updated_at)
                    / refresh_interval()
                )
                task = Task(
                    app,
                    db.query(User)
                    # .where(priority >= 1)
                    .where(User.id.not_in(get_targets()))
                    .where(User.followers_count >= 1)
                    .order_by(desc(priority))
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
                        "targets": [
                            {
                                "id": str(target.user_id),
                                "followers_count": target.followers_count,
                                "following_count": target.following_count
                            }
                            for target in task.targets
                        ]
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
                            if i == "followers" and not request.update_followers:
                                continue
                            if i == "following" and not request.update_following:
                                continue
                            setattr(user, i, getattr(request.target, i))
                        user.exists = True
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
        if task is not None and task in tasks:
            tasks.remove(task)
