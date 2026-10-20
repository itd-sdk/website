from asyncio import wait_for
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import count
from json import dumps, loads
from os import getenv
from pathlib import Path
from random import choices
from string import ascii_lowercase, digits
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket
from pydantic import BaseModel, ValidationError
from sqlalchemy import and_, case, desc, func, or_
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError

from app.logger import get_logger
from app.routers.api.ebdi.protocol import (
    PROTOCOL_VERSION,
    CloseCode,
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
from app.routers.api.ebdi.storage import save_comments, set_user_exists, upsert
from app.schemas import App, Post, User
from app.services.db import Session, get_db
from app.services.settings import get_settings

router = APIRouter(prefix="/websocket")
l = get_logger("ebdi.websocket")

POSTS_OVERLAP = timedelta(days=30)  # rescrape posts newer than last check minus this
POSTS_DELETE_MARGIN = timedelta(days=1)
# how often posts are rechecked by last activity, long_ago users are not checked at all
POSTS_INTERVALS = {
    "just_now": timedelta(days=1),
    "recently": timedelta(days=1),
    "minutes": timedelta(days=1),
    "hours": timedelta(days=1),
    "this_week": timedelta(days=3),
    "this_month": timedelta(days=14)
}
POSTS_INTERVAL_DEFAULT = timedelta(days=7)
# how often each task type is given out relative to the others, 0 turns it off;
# set from the admin panel and kept in a file across restarts
# posts are split in the first pass over a user and the rechecks of known ones
DEFAULT_TASK_WEIGHTS = {"update": 10, "posts_new": 10, "posts_recheck": 3, "create": 0}
MAX_TASK_WEIGHT = 10
task_weights: dict[str, int] | None = None


def weights_file() -> Path:
    # read on use, .env is loaded after the routers are imported
    return Path(getenv("EBDI_TASK_WEIGHTS", "cache/task_weights.json"))


def get_task_weights() -> dict[str, int]:
    global task_weights
    if task_weights is None:
        task_weights = dict(DEFAULT_TASK_WEIGHTS)
        try:
            stored = loads(weights_file().read_text())
            if "posts" in stored:
                # a file from before the posts split
                stored.setdefault("posts_new", stored["posts"])
            task_weights.update(
                {
                    key: int(value)
                    for key, value in stored.items()
                    if key in DEFAULT_TASK_WEIGHTS
                }
            )
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as error:
            l.warning("task weights file ignored: %r", error)
    return task_weights


def set_task_weights(weights: dict[str, int]) -> None:
    global task_weights
    task_weights = {**get_task_weights(), **weights}
    path = weights_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(task_weights))


@dataclass
class Task:
    app: App
    type: TaskType
    targets: list[User] = field(default_factory=list)
    prefix: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now())
    # posts task: the client sends every post newer than `since`, the stored
    # ones it did not send are gone from ITD
    since: datetime | None = None
    seen_posts: set[UUID] = field(default_factory=set)
    full: bool = False  # posts task: refetch every post, not only the recent ones
    renew_found_at: bool = False
    manual: bool = False  # sent from the admin panel
    done: int = 0  # handled targets, created users or saved posts
    # plain copies for the admin panel, it must not touch the connection's session
    usernames: list[str] = field(default_factory=list)
    target_posts: int = 0


tasks: list[Task] = []


@dataclass
class ManualTask:
    """Task queued from the admin panel, given out before the automatic ones"""

    type: TaskType
    client: str | None  # app name, None for the first client that asks
    query: str | None = None  # create: search query
    usernames: list[str] = field(default_factory=list)  # update or posts targets
    full: bool = False
    id: int = field(default_factory=count(1).__next__)
    created_at: datetime = field(default_factory=lambda: datetime.now())


manual_tasks: list[ManualTask] = []


def take_manual_task(db: Session, app: App) -> Task | None:
    for manual in list(manual_tasks):
        if manual.client not in (None, app.name):
            continue
        manual_tasks.remove(manual)
        if manual.type == TaskType.create:
            return Task(app, TaskType.create, prefix=manual.query, manual=True)
        targets = db.query(User).where(User.username.in_(manual.usernames)).all()
        if not targets:
            l.warning("manual task %s: no users %s", manual.id, manual.usernames)
            continue
        if manual.type == TaskType.posts:
            targets = targets[:1]
        return Task(app, manual.type, targets, full=manual.full, manual=True)
    return None


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


def update_task(db: Session, app: App) -> Task | None:
    priority = func.extract("epoch", func.now() - User.updated_at) / refresh_interval()
    targets = (
        db.query(User)
        .where(priority >= 0.8)
        .where(User.id.not_in(get_targets()))
        .where(User.followers_count >= 1)
        .order_by(desc(priority))
        .limit(20)
        .all()
    )
    return Task(app, TaskType.update, targets) if targets else None


def posts_new_task(db: Session, app: App) -> Task | None:
    """First pass over a user whose posts were never fetched (or were reset)"""
    target = (
        db.query(User)
        .where(User.exists.is_(True))
        .where(User.posts_count > 0)
        .where(User.posts_updated_at.is_(None))
        .where(User.id.not_in(get_targets()))
        # users with the most posts first, one or two posts can wait
        .order_by(User.posts_count.desc())
        .first()
    )
    return Task(app, TaskType.posts, [target]) if target is not None else None


def posts_recheck_task(db: Session, app: App) -> Task | None:
    """Recent posts of a known user, the most overdue one first"""
    interval = case(
        *[
            (User.last_seen == value, int(interval.total_seconds()))
            for value, interval in POSTS_INTERVALS.items()
        ],
        else_=int(POSTS_INTERVAL_DEFAULT.total_seconds())
    )
    overdue = func.extract("epoch", func.now() - User.posts_updated_at) / interval
    target = (
        db.query(User)
        .where(User.exists.is_(True))
        .where(User.posts_count > 0)
        # long inactive users are fetched once and not rechecked
        .where(User.last_seen.is_distinct_from("long_ago"))
        .where(User.posts_updated_at.is_not(None))
        .where(overdue >= 1)
        .where(User.id.not_in(get_targets()))
        .order_by(desc(overdue))
        .first()
    )
    return Task(app, TaskType.posts, [target]) if target is not None else None


def create_task(db: Session, app: App) -> Task | None:
    settings = get_settings(db)
    prefix = settings.search_cursor
    settings.search_cursor = increment_prefix(prefix)
    db.commit()
    return Task(app, TaskType.create, prefix=prefix)


TASK_BUILDERS = {
    "update": update_task,
    "posts_new": posts_new_task,
    "posts_recheck": posts_recheck_task,
    "create": create_task
}


def new_task(db: Session, app: App) -> Task | None:
    manual = take_manual_task(db, app)
    if manual is not None:
        return manual

    # a type is drawn by its weight, a type without work passes the turn on
    weights = get_task_weights()
    kinds = [kind for kind in TASK_BUILDERS if weights[kind] > 0]
    while kinds:
        kind = choices(kinds, [weights[k] for k in kinds])[0]
        task = TASK_BUILDERS[kind](db, app)
        if task is not None:
            return task
        kinds.remove(kind)
    return None


def task_response(db: Session, task: Task) -> BaseModel:
    match task.type:
        case TaskType.update:
            return UpdateTaskResponse(
                targets=[UpdateTarget(id=target.user_id) for target in task.targets]
            )
        case TaskType.create:
            assert task.prefix is not None
            return CreateTaskResponse(prefix=task.prefix)
        case TaskType.posts:
            user = task.targets[0]
            since = None
            known = db.query(Post.post_id, Post.comments_count).where(
                or_(
                    Post.author_id == user.user_id,
                    Post.wall_recipient_id == user.user_id
                )
            )
            # a reset posts_updated_at brings the posts back as if just found
            task.renew_found_at = user.posts_updated_at is None
            if user.posts_updated_at is not None and not task.full:
                since_local = user.posts_updated_at - POSTS_OVERLAP
                known = known.where(Post.created_at > since_local)
                task.since = since_local
                # naive local time -> aware utc, client compares it with post dates
                since = since_local.astimezone(timezone.utc)
            # a full rescan also refetches comments only where the count changed
            known_comments = dict(known.all())
            return PostsTaskResponse(
                target=PostsTarget(
                    id=user.user_id,
                    username=user.username,
                    since=since,
                    known_comments=known_comments
                )
            )


@dataclass
class Connection:
    websocket: WebSocket
    db: Session
    app: App
    task: Task | None = None
    name: str = ""  # app.name, the admin panel reads it from another thread
    connected_at: datetime = field(default_factory=lambda: datetime.now())
    last_message_at: datetime = field(default_factory=lambda: datetime.now())
    # what the client did since it connected: updated, created, posts, posts_done
    stats: Counter = field(default_factory=Counter)

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


# connected clients by app name, read by the admin panel
connections: dict[str, Connection] = {}


async def handle_task(connection: Connection, request: TaskRequest):
    if connection.task is not None and connection.task in tasks:
        tasks.remove(connection.task)

    connection.task = new_task(connection.db, connection.app)
    if connection.task is None:
        # the client waits for a reply, it sleeps on error and asks again
        await connection.error("no tasks")
        return
    tasks.append(connection.task)
    connection.task.usernames = [target.username for target in connection.task.targets]
    connection.task.target_posts = sum(t.posts_count for t in connection.task.targets)
    l.debug(
        "(%s) new task type=%s targets=%s",
        connection.app.name,
        connection.task.type.value,
        [target.username for target in connection.task.targets]
    )
    await connection.send(task_response(connection.db, connection.task))


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
        set_user_exists(conn.db, user, True)
    else:
        l.debug("(%s) < not exists", conn.app.name)
        set_user_exists(conn.db, user, False)
    user.updated_at = datetime.now()

    assert conn.task is not None
    conn.task.done += 1
    conn.stats["updated"] += 1
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
        conn.task.done += 1
        conn.stats["created"] += 1
        db.commit()

    await conn.send(CreatedResponse())


async def handle_known(conn: Connection, request: KnownRequest):
    known = [
        u.user_id
        for u in conn.db.query(User.user_id).where(User.user_id.in_(request.target_ids))
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
    assert conn.task is not None
    conn.task.seen_posts.add(post.post_id)
    row = {
        **post.model_dump(exclude={"comments", "comments_complete"}),
        "exists": True,
        "deleted_at": None,
        "updated_at": func.now()
    }
    if row["reposts_count"] is None:
        del row["reposts_count"]
    if conn.task.renew_found_at:
        # regular passes and manual full rescans keep the first found_at
        row["found_at"] = func.now()
    upsert(conn.db, Post, "post_id", [row])
    deleted = save_comments(
        conn.db, post.post_id, post.comments, post.comments_complete
    )
    if deleted:
        l.debug(
            "(%s) post %s: %s comments deleted", conn.app.name, post.post_id, deleted
        )
    conn.task.done += 1
    conn.stats["posts"] += 1
    conn.db.commit()
    await conn.send(PostSavedResponse())


def mark_deleted_posts(db: Session, task: Task | None, user: User) -> None:
    assert task is not None
    # posts shown on the user's profile: own ones and the ones others left on it;
    # own posts on other walls do not show up there, so they are left alone
    query = (
        db.query(Post)
        .where(Post.exists.is_(True))
        .where(
            or_(
                Post.wall_recipient_id == user.user_id,
                and_(Post.author_id == user.user_id, Post.wall_recipient_id.is_(None))
            )
        )
        .where(Post.post_id.not_in(task.seen_posts))
    )
    if task.since is not None:
        # margin covers a timezone mismatch between the app and the database
        query = query.where(Post.created_at > task.since + POSTS_DELETE_MARGIN)
    deleted = query.update(
        {Post.exists: False, Post.deleted_at: func.now()}, synchronize_session=False
    )
    if deleted:
        l.debug("(%s) %s posts deleted", user.username, deleted)


async def handle_posts_done(conn: Connection, request: PostsDoneRequest):
    user = await conn.get_target(TaskType.posts, request.target_id)
    if user is None:
        return

    l.debug("(%s) < posts done %s", conn.app.name, user.username)
    user.posts_updated_at = datetime.now()
    if not request.target_exists:
        set_user_exists(conn.db, user, False)
    else:
        mark_deleted_posts(conn.db, conn.task, user)
    conn.stats["posts_done"] += 1
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
    if app.name in connections or app.name in [task.app.name for task in tasks]:
        l.info("decline reason=already exists")
        await websocket.close(CloseCode.task_exists, "task already exists")
        return

    await websocket.accept()
    conn = Connection(websocket, db, app, name=app.name)
    connections[app.name] = conn
    try:
        while True:
            timeout = 60
            if conn.task is not None and conn.task.type == TaskType.posts:
                timeout = 600
            try:
                data = await wait_for(websocket.receive_text(), timeout)
            except TimeoutError:
                l.error("(%s) timeout", app.name)
                await websocket.close(CloseCode.timeout, "timeout")
                return

            conn.last_message_at = datetime.now()
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
        if connections.get(app.name) is conn:
            del connections[app.name]
        if conn.task is not None and conn.task in tasks:
            tasks.remove(conn.task)
