from asyncio import wait_for
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from string import ascii_lowercase, digits
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket
from pydantic import BaseModel
from sqlalchemy import case, desc, func
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError

from app.logger import get_logger
from app.schemas import App, User
from app.services.db import Session, get_db
from app.services.settings import get_settings

router = APIRouter(prefix="/websocket")
l = get_logger("ebdi.websocket")


@dataclass
class Task:
    app: App
    targets: list[User] | None = None
    type: str = "update"
    prefix: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now())


tasks: list[Task] = []


def get_targets():
    targets = []
    for task in tasks:
        targets.extend([target.id for target in task.targets or []])
    return targets


def remove_expired_tasks():
    now = datetime.now()
    expired = [t for t in tasks if now - t.started_at > timedelta(minutes=15)]
    for t in expired:
        l.warning("expire task for %s", t.app.name)
        tasks.remove(t)


ALPHABET = ascii_lowercase + digits + "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"


def increment_prefix(prefix: str) -> str:
    chars = list(prefix)
    for i in reversed(range(len(chars))):
        index = ALPHABET.index(chars[i]) + 1
        if index < len(ALPHABET):
            chars[i] = ALPHABET[index]
            return "".join(chars)
        # carry over: reset this position and bump the one before it
        chars[i] = ALPHABET[0]
    # wrapped around, start the cycle over
    return ALPHABET[0] * len(prefix)


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
    user_id: UUID | None = None  # for create


class WSRequestType(Enum):
    task = "task"
    update = "update"
    create = "create"
    known = "known"


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
    target_ids: list[UUID] | None = None


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
                update_query = (
                    db.query(User)
                    .where(priority >= 0.8)
                    .where(User.id.not_in(get_targets()))
                    .where(User.followers_count >= 1)
                    .order_by(desc(priority))
                    .limit(20)
                    .all()
                )
                if update_query:
                    task = Task(app, update_query, type="update")
                else:
                    settings = get_settings(db)
                    prefix = settings.search_cursor
                    settings.search_cursor = increment_prefix(prefix)
                    db.commit()
                    task = Task(app, type="create", prefix=prefix)

                l.debug("(%s) new task", app.name)
                # if not task.targets:
                #     l.warning("(%s) no targets", app.name)
                #     await websocket.send_json({"type": "done"})
                #     return

                tasks.append(task)

                await websocket.send_json(
                    {
                        "type": "task",
                        "task_type": task.type,
                        "prefix": task.prefix,
                        "target_type": WSTargetType.user.value,
                        "targets": [
                            {
                                "id": str(target.user_id),
                                "followers_count": target.followers_count,
                                "following_count": target.following_count
                            }
                            for target in task.targets or []
                        ]
                    }
                )

            elif request.type == WSRequestType.update:
                assert request.target_type

                if task is None:
                    l.error("(%s) no task", app.name)
                    await websocket.send_json({"type": "error", "detail": "no task"})
                    continue

                if request.target_type != WSTargetType.user:
                    l.error("(%s) invalid target type", app.name)
                    await websocket.send_json(
                        {"type": "error", "detail": "user not in task targets"}
                    )
                    continue

                assert request.target_id
                user = next(
                    (
                        user
                        for user in task.targets or []
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

            elif request.type == WSRequestType.create:
                assert request.target

                if task is None or task.prefix is None:
                    await websocket.send_json({"type": "error", "detail": "no task"})
                    continue

                if request.target_type != WSTargetType.user:
                    l.error("(%s) invalid target type", app.name)
                    await websocket.send_json(
                        {"type": "error", "detail": "user not in task targets"}
                    )
                    continue

                user = request.target
                if db.query(User).where(User.user_id == user.user_id).first() is None:
                    l.debug("(%s) < %s", app.name, user.username)
                    db_user = User()
                    for i in user.model_fields_set:
                        setattr(db_user, i, getattr(user, i))
                    db_user.exists = True
                    db_user.updated_at = datetime.now()
                    db.add(db_user)
                    app.added += 1
                    db.commit()

                await websocket.send_json({"type": "created"})
                # else:
                #     await websocket.send_json(
                #         {"type": "error", "detail": "already exists"}
                #     )

            elif request.type == WSRequestType.known:
                if request.target_ids is None:
                    await websocket.send_json(
                        {"type": "error", "detail": "no target_ids"}
                    )
                    continue
                known = [
                    str(u.user_id)
                    for u in db.query(User.user_id).where(
                        User.user_id.in_(request.target_ids)
                    )
                ]
                await websocket.send_json({"type": "known", "user_ids": known})

            else:
                l.error("(%s) invalid type", app.name)
                await websocket.send_json({"type": "error", "detail": "invalid type"})

    except (WebSocketDisconnect, ConnectionClosedError):
        l.warning("(%s) disconnect", app.name)
    finally:
        if task is not None and task in tasks:
            tasks.remove(task)
