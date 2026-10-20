"""Admin panel API: connected scraper clients, progress and manual tasks.

Disabled unless EBDI_ADMIN_TOKEN is set, requests carry it as a bearer token.
"""

from datetime import datetime, timedelta
from hmac import compare_digest
from os import getenv
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func

from app.routers.api.ebdi import websocket
from app.routers.api.ebdi.dates import LocalDatetime
from app.routers.api.ebdi.protocol import TaskType
from app.schemas import App, Comment, Post, User
from app.services.db import Session, get_db
from app.services.limiter import get_limiter

router = APIRouter(prefix="/admin")

HISTORY_HOURS = 48
UPDATE_CHUNK = 20  # users in one update task, like the automatic ones
COUNTS_TTL = timedelta(seconds=30)


def require_admin(authorization: str = Header("")):
    # read on use, .env is loaded after the routers are imported
    token = getenv("EBDI_ADMIN_TOKEN", "")
    if not token:
        raise HTTPException(403, "admin api is disabled")
    if not compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "invalid admin token")


class TaskInfo(BaseModel):
    type: TaskType
    manual: bool
    started_at: LocalDatetime
    targets: list[str]  # usernames
    query: str | None  # create: search query
    since: LocalDatetime | None  # posts: only posts newer than this
    full: bool
    done: int
    total: int | None  # None when the size is not known (create)


class ClientInfo(BaseModel):
    name: str
    address: str | None
    connected_at: LocalDatetime
    last_message_at: LocalDatetime
    task: TaskInfo | None
    stats: dict[str, int]  # since the client connected
    added: int  # all time
    refreshed: int


class AppInfo(BaseModel):
    name: str
    added: int
    refreshed: int
    connected: bool


class QueuedTask(BaseModel):
    id: int
    type: TaskType
    client: str | None
    query: str | None
    usernames: list[str]
    full: bool
    created_at: LocalDatetime


class Counts(BaseModel):
    users: int
    users_found_today: int
    users_updated_today: int
    posts: int
    posts_found_today: int
    posts_updated_today: int
    comments: int
    comments_found_today: int


class HistoryPoint(BaseModel):
    hour: LocalDatetime
    users_found: int = 0
    users_updated: int = 0  # by the last update, older updates are overwritten
    posts_found: int = 0
    posts_updated: int = 0
    comments_found: int = 0


class AdminState(BaseModel):
    server_time: LocalDatetime
    clients: list[ClientInfo]
    apps: list[AppInfo]
    queue: list[QueuedTask]
    counts: Counts
    history: list[HistoryPoint]
    weights: dict[TaskType, int]  # how often each task type is given out, 0 is off
    max_weight: int


def task_info(task: websocket.Task) -> TaskInfo:
    total = None
    if task.type == TaskType.update:
        total = len(task.targets)
    elif task.type == TaskType.posts and task.since is None:
        # a partial pass sends only the recent posts, its size is not known
        total = task.target_posts
    return TaskInfo(
        type=task.type,
        manual=task.manual,
        started_at=task.started_at,
        targets=task.usernames,
        query=task.prefix,
        since=task.since,
        full=task.full,
        done=task.done,
        total=total
    )


def client_info(conn: websocket.Connection, app: App | None) -> ClientInfo:
    # the connection's own orm objects belong to another thread's session,
    # only plain fields are read here
    client = conn.websocket.client
    return ClientInfo(
        name=conn.name,
        address=f"{client.host}:{client.port}" if client else None,
        connected_at=conn.connected_at,
        last_message_at=conn.last_message_at,
        task=task_info(conn.task) if conn.task else None,
        stats=dict(conn.stats),
        added=app.added if app else 0,
        refreshed=app.refreshed if app else 0
    )


def queued(manual: websocket.ManualTask) -> QueuedTask:
    return QueuedTask(
        id=manual.id,
        type=manual.type,
        client=manual.client,
        query=manual.query,
        usernames=manual.usernames,
        full=manual.full,
        created_at=manual.created_at
    )


def hourly(db: Session, column, since: datetime) -> dict[datetime, int]:
    hour = func.date_trunc("hour", column)
    rows = db.query(hour, func.count()).where(column >= since).group_by(hour)
    return dict(rows.all())


def count_since(db: Session, column, since: datetime) -> int:
    return db.query(func.count()).where(column >= since).scalar() or 0


counts_cache: tuple[datetime, Counts, list[HistoryPoint]] | None = None


def get_counts(db: Session) -> tuple[Counts, list[HistoryPoint]]:
    global counts_cache
    now = datetime.now()
    if counts_cache and now - counts_cache[0] < COUNTS_TTL:
        return counts_cache[1], counts_cache[2]

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    counts = Counts(
        users=db.query(func.count(User.id)).scalar() or 0,
        users_found_today=count_since(db, User.found_at, today),
        users_updated_today=count_since(db, User.updated_at, today),
        posts=db.query(func.count(Post.id)).scalar() or 0,
        posts_found_today=count_since(db, Post.found_at, today),
        posts_updated_today=count_since(db, Post.updated_at, today),
        comments=db.query(func.count(Comment.id)).scalar() or 0,
        comments_found_today=count_since(db, Comment.found_at, today)
    )

    start = (now - timedelta(hours=HISTORY_HOURS - 1)).replace(
        minute=0, second=0, microsecond=0
    )
    series = {
        "users_found": hourly(db, User.found_at, start),
        "users_updated": hourly(db, User.updated_at, start),
        "posts_found": hourly(db, Post.found_at, start),
        "posts_updated": hourly(db, Post.updated_at, start),
        "comments_found": hourly(db, Comment.found_at, start)
    }
    history = []
    for i in range(HISTORY_HOURS):
        hour = start + timedelta(hours=i)
        history.append(
            HistoryPoint(
                hour=hour, **{key: rows.get(hour, 0) for key, rows in series.items()}
            )
        )
    counts_cache = (now, counts, history)
    return counts, history


@router.get("/state", response_model=AdminState, dependencies=[Depends(require_admin)])
@get_limiter().exempt
def api_get_ebdi_admin_state(request: Request, db: Session = Depends(get_db)):
    counts, history = get_counts(db)
    connections = list(websocket.connections.values())
    apps = {app.name: app for app in db.query(App).order_by(App.name)}
    return AdminState(
        server_time=datetime.now(),
        clients=[client_info(conn, apps.get(conn.name)) for conn in connections],
        apps=[
            AppInfo(
                name=app.name,
                added=app.added,
                refreshed=app.refreshed,
                connected=app.name in websocket.connections
            )
            for app in apps.values()
        ],
        queue=[queued(manual) for manual in websocket.manual_tasks],
        counts=counts,
        history=history,
        weights=websocket.get_task_weights(),
        max_weight=websocket.MAX_TASK_WEIGHT
    )


class NewTaskRequest(BaseModel):
    type: TaskType
    client: str | None = None  # app name, None for the first client that asks
    query: str | None = Field(None, max_length=100)  # create
    usernames: list[str] = Field([], max_length=1000)  # update; posts takes one
    full: bool = False  # posts: refetch every post


class NewTaskResponse(BaseModel):
    queued: list[QueuedTask]
    missing: list[str]  # usernames that are not in the database


@router.post(
    "/tasks", response_model=NewTaskResponse, dependencies=[Depends(require_admin)]
)
@get_limiter().exempt
def api_post_ebdi_admin_task(
    request: Request, body: NewTaskRequest, db: Session = Depends(get_db)
):
    if body.client and not db.query(App).where(App.name == body.client).first():
        raise HTTPException(404, "unknown client")

    if body.type == TaskType.create:
        query = (body.query or "").strip()
        if not query:
            raise HTTPException(422, "create task needs a search query")
        tasks = [websocket.ManualTask(TaskType.create, body.client, query=query)]
        missing = []
    else:
        names = list(dict.fromkeys(n.strip().removeprefix("@") for n in body.usernames))
        names = [n for n in names if n]
        if body.type == TaskType.posts:
            names = names[:1]
        if not names:
            raise HTTPException(422, "task needs usernames")
        found = {
            name for (name,) in db.query(User.username).where(User.username.in_(names))
        }
        missing = [n for n in names if n not in found]
        known = [n for n in names if n in found]
        tasks = [
            websocket.ManualTask(
                body.type,
                body.client,
                usernames=known[i : i + UPDATE_CHUNK],
                full=body.full
            )
            for i in range(0, len(known), UPDATE_CHUNK)
        ]
    websocket.manual_tasks.extend(tasks)
    return NewTaskResponse(queued=[queued(task) for task in tasks], missing=missing)


@router.delete("/tasks/{task_id}", dependencies=[Depends(require_admin)])
@get_limiter().exempt
def api_delete_ebdi_admin_task(request: Request, task_id: int):
    for manual in websocket.manual_tasks:
        if manual.id == task_id:
            websocket.manual_tasks.remove(manual)
            return {"deleted": task_id}
    raise HTTPException(404, "task not in the queue")


@router.put(
    "/weights",
    response_model=dict[TaskType, int],
    dependencies=[Depends(require_admin)]
)
@get_limiter().exempt
def api_put_ebdi_admin_weights(
    request: Request,
    body: dict[TaskType, Annotated[int, Field(ge=0, le=websocket.MAX_TASK_WEIGHT)]]
):
    websocket.set_task_weights(body)
    return websocket.get_task_weights()
