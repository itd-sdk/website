from asyncio import wait_for
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import aliased
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError

from app.logger import get_logger
from app.schemas import App, User
from app.services.db import Session, get_db
from app.services.limiter import get_limiter

router = APIRouter(prefix="/ebdi")
l = get_logger("ebdi")


@dataclass
class Task:
    app: App
    targets: list[User]
    type: str = "update"
    started_at: datetime = field(default_factory=lambda: datetime.now())


to_refresh: set[User] = set()
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
    exists: bool
    # позиция в отфильтрованном списке (1-based), из неё фронт считает
    # офсет батча при прыжке из поиска
    position: int = 0
    # место в глобальном топе по выбранной сортировке, без учёта фильтров,
    # удалённые пропущены (у них None)
    global_rank: int | None = None
    # место с учётом фильтров, удалённые пропущены (у них None)
    filtered_rank: int | None = None


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

                if to_refresh:
                    task = Task(app, list(to_refresh))
                    to_refresh.clear()
                else:
                    task = Task(
                        app,
                        db.query(User)
                        .order_by(desc(User.followers_count))
                        .where(User.updated_at < datetime.now() - timedelta(days=3))
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


def verify_app_token(app_token: str, db: Session = Depends(get_db)):
    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        raise HTTPException(detail="invalid app token", status_code=401)
    return app


def build_users_query(
    db: Session,
    order: UserOrder,  # такая небольшая пасхалка, можно сделать ордер по дате обновления
    descending: bool,
    clan: str | None,
    verified: bool | None,
    has_itdp: bool | None,
    has_checkmark: bool | None,
    min_followers: int | None,
    exists: bool | None
):
    col = getattr(User, order.value)
    # глобальное место считается до фильтров, по всей таблице;
    # partition by exists — удалённые не занимают места в топе
    inner = db.query(
        User,
        func.row_number()
        .over(
            partition_by=User.exists,
            order_by=(desc(col) if descending else col.asc(), User.id)
        )
        .label("global_rank"),
        func.row_number()
        .over(order_by=(desc(col) if descending else col.asc(), User.id))
        .label("global_position")
    ).subquery()
    u = aliased(User, inner, adapt_on_names=True)
    ordered_col = getattr(u, order.value)
    order_by = (desc(ordered_col) if descending else ordered_col.asc(), u.id)

    # оконные функции во внешнем запросе применяются после WHERE,
    # поэтому position и filtered_rank учитывают фильтры
    query = db.query(
        u,
        inner.c.global_rank,
        inner.c.global_position,
        func.row_number().over(order_by=order_by).label("position"),
        func.row_number()
        .over(partition_by=u.exists, order_by=order_by)
        .label("filtered_rank")
    )
    if clan:
        query = query.where(u.avatar == clan)
    if verified is not None:
        query = query.where(u.verified == verified)
    if has_itdp is not None:
        query = query.where(u.has_itdp == has_itdp)
    if has_checkmark is not None:
        checkmark = u.display_name.contains("✓")
        query = query.where(checkmark if has_checkmark else ~checkmark)
    if min_followers is not None:
        query = query.where(u.followers_count > min_followers)
    if exists is not None:
        query = query.where(u.exists == exists)
    return query.order_by(*order_by), u


def serialize_user(row, unfiltered: bool = False) -> UserResponse:
    user, global_rank, global_position, position, filtered_rank = row
    response = UserResponse.model_validate(user, from_attributes=True)
    # оконные функции внешнего запроса считаются после его WHERE, поэтому
    # при поиске (ilike во внешнем WHERE) position/filtered_rank были бы
    # номерами внутри выдачи -- берём значения из внутреннего подзапроса
    response.position = global_position if unfiltered else position
    response.global_rank = global_rank if user.exists else None
    if unfiltered:
        response.filtered_rank = response.global_rank
    else:
        response.filtered_rank = filtered_rank if user.exists else None
    return response


@router.get("/users", response_model=list[UserResponse])
@get_limiter().limit("10/minute")
def api_get_ebdi_users(
    request: Request,
    offset: int = 0,
    order: UserOrder = UserOrder.followers,
    descending: bool = True,
    clan: str | None = None,
    verified: bool | None = None,
    has_itdp: bool | None = None,
    has_checkmark: bool | None = None,
    min_followers: int | None = None,
    exists: bool | None = None,
    db: Session = Depends(get_db)
):
    query, _ = build_users_query(
        db,
        order,
        descending,
        clan,
        verified,
        has_itdp,
        has_checkmark,
        min_followers,
        exists
    )
    return [serialize_user(row) for row in query.offset(offset).limit(100).all()]


@router.post("/users/{id}/refresh", status_code=204)
@get_limiter().limit("5/minute")
def api_post_ebdi_users_refresh(
    request: Request, id: UUID, db: Session = Depends(get_db)
):
    l.info("postpone user refresh id=%s", id)
    user = db.query(User).where(User.user_id == id).first()
    if not user:
        l.warning("user not found")
        return JSONResponse({"detail": "user not found"}, 404)
    to_refresh.add(user)


# @router.post("/users")
# def api_post_ebdi(
#     id: UUID,
#     body: UserBody,
#     app: App = Depends(verify_app_token),
#     db: Session = Depends(get_db)
# ):

#     if db.query(User).where(User.user_id == id).first() is not None:
#         return JSONResponse({"detail": "user already exists"}, 409)

#     user = User(
#         user_id=id,
#         created_at=body.created_at,
#         username=body.username,
#         display_name=body.display_name,
#         followers=body.followers,
#         following=body.following,
#         followers_count=body.followers_count,
#         following_count=body.following_count,
#         posts_count=body.posts_count,
#         verified=body.verified,
#         avatar=body.avatar
#     )
#     db.add(user)
#     db.commit()
#     db.refresh(user)
#     app.added += 1
#     return user


@router.get("/users/search")
def api_get_ebdi_user_search(
    query: str,
    order: UserOrder = UserOrder.followers,
    descending: bool = True,
    db: Session = Depends(get_db)
):
    # поиск всегда идёт по всей базе без фильтров, поэтому position
    # совпадает с нефильтрованным списком в выбранной сортировке
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    users_query, u = build_users_query(
        db, order, descending, None, None, None, None, None, None
    )
    rows = (
        users_query.where(
            or_(
                u.username.ilike(pattern, escape="\\"),
                u.display_name.ilike(pattern, escape="\\")
            )
        )
        .limit(20)
        .all()
    )
    return {"results": [serialize_user(row, unfiltered=True) for row in rows]}
