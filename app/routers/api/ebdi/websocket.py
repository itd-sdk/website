from asyncio import wait_for
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from string import ascii_lowercase, digits
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket
from pydantic import BaseModel, ValidationError
from sqlalchemy import case, desc, func
from sqlalchemy.dialects.postgresql import insert
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError

from app.logger import get_logger
from app.routers.api.ebdi.protocol import (
    PROTOCOL_VERSION,
    CloseCode,
    CommentBody,
    CreatedResponse,
    CreateRequest,
    CreateTaskResponse,
    ErrorResponse,
    KnownRequest,
    KnownResponse,
    PostRequest,
    PostSavedResponse,
    PostsDoneRequest,
    PostsTarget,
    PostsTaskResponse,
    PostsUpdatedResponse,
    TaskRequest,
    TaskType,
    UpdatedResponse,
    UpdateRequest,
    UpdateTarget,
    UpdateTaskResponse,
    client_message
)
from app.schemas import App, Comment, Post, User
from app.services.db import Session, get_db
from app.services.settings import get_settings

router = APIRouter(prefix="/websocket")
l = get_logger("ebdi.websocket")

POSTS_EVERY = 2  # every Nth task without user updates scrapes posts, others discover users
POSTS_OVERLAP = timedelta(days=30)  # rescrape posts newer than last check minus this
POSTS_TIMEOUT = 600  # one post with all comments and replies can take a while
idle_counter = 0


@dataclass
class Task:
    app: App
    type: TaskType
    targets: list[User] = field(default_factory=list)
    prefix: str | None = None
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


def flatten_comments(
    comments: list[CommentBody], post_id: UUID, parent_id: UUID | None = None
) -> Iterator[dict]:
    # parents always go before their replies so the parent_id fk is satisfied
    for comment in comments:
        yield {
            **comment.model_dump(exclude={"replies"}),
            "post_id": post_id,
            "parent_id": parent_id
        }
        yield from flatten_comments(comment.replies, post_id, comment.comment_id)


def upsert(db: Session, model: type[Post] | type[Comment], key: str, rows: list[dict]):
    # chunks keep a single statement below the postgres bind parameters limit
    for i in range(0, len(rows), 1000):
        stmt = insert(model).values(rows[i : i + 1000])
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=[key],
                set_={c: stmt.excluded[c] for c in rows[0] if c != key}
            )
        )


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


def new_task(db: Session, app: App) -> Task:
    global idle_counter

    priority = (
        func.extract("epoch", func.now() - User.updated_at) / refresh_interval()
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
        return Task(app, TaskType.update, update_query)

    idle_counter += 1
    if idle_counter % POSTS_EVERY == 0:
        posts_user = (
            db.query(User)
            .where(User.exists.is_(True))
            .where(User.posts_count > 0)
            .where(User.last_seen.is_distinct_from("long_ago"))
            .where(User.id.not_in(get_targets()))
            .order_by(User.posts_updated_at.asc().nulls_first())
            .first()
        )
        if posts_user is not None:
            return Task(app, TaskType.posts, [posts_user])

    settings = get_settings(db)
    prefix = settings.search_cursor
    settings.search_cursor = increment_prefix(prefix)
    db.commit()
    return Task(app, TaskType.create, prefix=prefix)


def task_response(task: Task) -> BaseModel:
    match task.type:
        case TaskType.update:
            return UpdateTaskResponse(
                targets=[
                    UpdateTarget(id=target.user_id) for target in task.targets
                ]
            )
        case TaskType.create:
            assert task.prefix is not None
            return CreateTaskResponse(prefix=task.prefix)
        case TaskType.posts:
            user = task.targets[0]
            since = None
            if user.posts_updated_at is not None:
                # naive local time -> aware utc, client compares it with post dates
                since = (user.posts_updated_at - POSTS_OVERLAP).astimezone(timezone.utc)
            return PostsTaskResponse(
                target=PostsTarget(id=user.user_id, username=user.username, since=since)
            )


@dataclass
class Connection:
    websocket: WebSocket
    db: Session
    app: App
    task: Task | None = None

    async def send(self, message: BaseModel) -> None:
        await self.websocket.send_text(message.model_dump_json())

    async def error(self, detail: str) -> None:
        l.error("(%s) %s", self.app.name, detail)
        await self.send(ErrorResponse(detail=detail))

    async def get_target(self, task_type: TaskType, target_id: UUID) -> User | None:
        """Find the user in the current task, reply with an error if not found"""
        if self.task is None or self.task.type != task_type:
            await self.error("no task")
            return None
        user = next((u for u in self.task.targets if u.user_id == target_id), None)
        if user is None:
            await self.error("user not in task targets")
        return user


async def handle_task(conn: Connection, request: TaskRequest):
    if conn.task is not None and conn.task in tasks:
        tasks.remove(conn.task)

    conn.task = new_task(conn.db, conn.app)
    tasks.append(conn.task)
    l.debug("(%s) new %s task", conn.app.name, conn.task.type.value)
    await conn.send(task_response(conn.task))


async def handle_update(conn: Connection, request: UpdateRequest):
    user = await conn.get_target(TaskType.update, request.target_id)
    if user is None:
        return

    if request.target is not None:
        l.debug("(%s) < %s", conn.app.name, request.target.username)
        for i in request.target.model_fields_set:
            if i == "avatar":
                continue
            setattr(user, i, getattr(request.target, i))
        user.exists = True
    else:
        l.debug("(%s) < not exists", conn.app.name)
        user.exists = False
    user.updated_at = datetime.now()

    conn.app.refreshed += 1
    conn.db.commit()
    await conn.send(UpdatedResponse())


async def handle_create(conn: Connection, request: CreateRequest):
    if conn.task is None or conn.task.type != TaskType.create:
        await conn.error("no task")
        return

    user = request.target
    db = conn.db
    if db.query(User).where(User.user_id == user.user_id).first() is None:
        l.debug("(%s) < %s", conn.app.name, user.username)
        db.add(
            User(
                **user.model_dump(),
                followers=[],  # followers are not scraped for now
                following=[],
                exists=True,
                updated_at=datetime.now()
            )
        )
        conn.app.added += 1
        db.commit()

    await conn.send(CreatedResponse())


async def handle_known(conn: Connection, request: KnownRequest):
    known = [
        u.user_id
        for u in conn.db.query(User.user_id).where(
            User.user_id.in_(request.target_ids)
        )
    ]
    await conn.send(KnownResponse(user_ids=known))


async def handle_post(conn: Connection, request: PostRequest):
    user = await conn.get_target(TaskType.posts, request.target_id)
    if user is None:
        return

    post = request.post
    if user.user_id not in (post.author_id, post.wall_recipient_id):
        await conn.error("post not from target user")
        return

    l.debug("(%s) < post %s", conn.app.name, post.post_id)
    upsert(conn.db, Post, "post_id", [post.model_dump(exclude={"comments"})])
    # same comment can come twice (pagination shifts), one insert
    # with duplicate keys fails, so keep the first occurrence
    comments: dict[UUID, dict] = {}
    for row in flatten_comments(post.comments, post.post_id):
        comments.setdefault(row["comment_id"], row)
    upsert(conn.db, Comment, "comment_id", list(comments.values()))
    conn.db.commit()
    await conn.send(PostSavedResponse())


async def handle_posts_done(conn: Connection, request: PostsDoneRequest):
    user = await conn.get_target(TaskType.posts, request.target_id)
    if user is None:
        return

    l.debug("(%s) < posts done %s", conn.app.name, user.username)
    user.posts_updated_at = datetime.now()
    conn.app.refreshed += 1
    conn.db.commit()
    await conn.send(PostsUpdatedResponse())


@router.websocket("/")
async def api_websocket_ebdi(
    websocket: WebSocket,
    app_token: str,
    version: int | None = None,
    db: Session = Depends(get_db)
):
    l.info("init connection")
    remove_expired_tasks()

    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        l.info("decline reason=invalid token")
        await websocket.close(CloseCode.invalid_token, "invalid app token")
        return
    if version != PROTOCOL_VERSION:
        l.info("decline reason=outdated client version=%s", version)
        # close reason reaches the client only after accept
        await websocket.accept()
        await websocket.close(
            CloseCode.outdated_client,
            f"client version {version} is not supported, update to {PROTOCOL_VERSION}"
        )
        return
    if app.name in [task.app.name for task in tasks]:
        l.info("decline reason=already exists")
        await websocket.close(CloseCode.task_exists, "task already exists")
        return

    await websocket.accept()
    conn = Connection(websocket, db, app)
    try:
        while True:
            timeout = 60
            if conn.task is not None and conn.task.type == TaskType.posts:
                timeout = POSTS_TIMEOUT
            try:
                data = await wait_for(websocket.receive_text(), timeout)
            except TimeoutError:
                l.error("(%s) timeout", app.name)
                await websocket.close(CloseCode.timeout, "timeout")
                return

            try:
                request = client_message.validate_json(data)
            except ValidationError as e:
                await conn.error(f"invalid message: {e}")
                continue

            match request:
                case TaskRequest():
                    await handle_task(conn, request)
                case UpdateRequest():
                    await handle_update(conn, request)
                case CreateRequest():
                    await handle_create(conn, request)
                case KnownRequest():
                    await handle_known(conn, request)
                case PostRequest():
                    await handle_post(conn, request)
                case PostsDoneRequest():
                    await handle_posts_done(conn, request)

    except (WebSocketDisconnect, ConnectionClosedError):
        l.warning("(%s) disconnect", app.name)
    finally:
        if conn.task is not None and conn.task in tasks:
            tasks.remove(conn.task)
