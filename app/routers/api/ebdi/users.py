from datetime import datetime, timedelta
from enum import Enum
from json import dumps
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import case, desc, func, or_
from sqlalchemy.orm import aliased

from app.routers.api.ebdi.websocket import UserBody
from app.schemas import App, User
from app.services.db import Session, get_db
from app.services.limiter import get_limiter

router = APIRouter(prefix="/users")


class UserResponse(UserBody):
    id: int
    user_id: UUID
    found_at: datetime
    has_itdp: bool
    exists: bool
    # позиция в отфильтрованном списке (1-based), из неё фронт считает офсет батча при прыжке из поиска
    position: int = 0
    # место в глобальном топе по выбранной сортировке, без учёта фильтров, удалённые пропущены (у них None)
    global_rank: int | None = None
    # место с учётом фильтров, удалённые пропущены (у них None)
    filtered_rank: int | None = None


class UserRankResponse(BaseModel):
    total: int
    place: int | None = None
    to_next: int | None = None
    to_top_100: int | None = None


class UserRanksResponse(BaseModel):
    followers: UserRankResponse
    following: UserRankResponse
    posts: UserRankResponse


class UserOrder(Enum):
    followers = "followers_count"
    following = "following_count"
    posts_count = "posts_count"
    created_at = "created_at"
    found_at = "found_at"
    updated_at = "updated_at"


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
    exists: bool | None
):
    col = getattr(User, order.value)
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
    if exists is not None:
        query = query.where(u.exists == exists)
    return query.order_by(*order_by), u


def serialize_user(row, unfiltered: bool = False) -> UserResponse:
    user, global_rank, global_position, position, filtered_rank = row
    response = UserResponse.model_validate(user, from_attributes=True)
    response.position = global_position if unfiltered else position
    response.global_rank = global_rank if user.exists else None
    if unfiltered:
        response.filtered_rank = response.global_rank
    else:
        response.filtered_rank = filtered_rank if user.exists else None
    return response


@router.get("", response_model=list[UserResponse])
@get_limiter().limit("15/minute")
def api_get_ebdi_users(
    request: Request,
    offset: int = 0,
    order: UserOrder = UserOrder.followers,
    descending: bool = True,
    clan: str | None = None,
    verified: bool | None = None,
    has_itdp: bool | None = None,
    exists: bool | None = None,
    db: Session = Depends(get_db)
):
    query, _ = build_users_query(
        db, order, descending, clan, verified, has_itdp, exists
    )
    return [serialize_user(row) for row in query.offset(offset).limit(100).all()]


@router.get("/{id}/ranks")
@get_limiter().limit("20/minute")
def api_get_ebdi_user_ranks(request: Request, id: int, db: Session = Depends(get_db)):
    ranks = db.query(
        User,
        func.row_number()
        .over(partition_by=User.exists, order_by=(User.followers_count.desc(), User.id))
        .label("followers_place"),
        func.row_number()
        .over(partition_by=User.exists, order_by=(User.following_count.desc(), User.id))
        .label("following_place"),
        func.row_number()
        .over(partition_by=User.exists, order_by=(User.posts_count.desc(), User.id))
        .label("posts_place")
    ).subquery()
    u = aliased(User, ranks, adapt_on_names=True)

    row = (
        db.query(
            u, ranks.c.followers_place, ranks.c.following_place, ranks.c.posts_place
        )
        .where(u.id == id)
        .first()
    )
    if row is None:
        raise HTTPException(detail="not found", status_code=404)
    user, followers_place, following_place, posts_place = row

    if not user.exists:
        return UserRanksResponse(
            followers=UserRankResponse(
                total=user.followers_count, place=None, to_next=None, to_top_100=None
            ),
            following=UserRankResponse(
                total=user.following_count, place=None, to_next=None, to_top_100=None
            ),
            posts=UserRankResponse(
                total=user.posts_count, place=None, to_next=None, to_top_100=None
            )
        )

    next_followers, next_following, next_posts = db.query(
        func.min(
            case(
                (
                    ranks.c.followers_count > user.followers_count,
                    ranks.c.followers_count
                )
            )
        ),
        func.min(
            case(
                (
                    ranks.c.following_count > user.following_count,
                    ranks.c.following_count
                )
            )
        ),
        func.min(case((ranks.c.posts_count > user.posts_count, ranks.c.posts_count)))
    ).one()

    top_followers, top_following, top_posts = db.query(
        func.max(case((ranks.c.followers_place == 100, ranks.c.followers_count))),
        func.max(case((ranks.c.following_place == 100, ranks.c.following_count))),
        func.max(case((ranks.c.posts_place == 100, ranks.c.posts_count)))
    ).one()

    def gap(
        target: int | None, current: int, place: int, only_outside_top: bool = False
    ):
        if target is None or (only_outside_top and place <= 100):
            return None
        return target - current

    return UserRanksResponse(
        followers=UserRankResponse(
            total=user.followers_count,
            place=followers_place,
            to_next=gap(next_followers, user.followers_count, followers_place),
            to_top_100=gap(top_followers, user.followers_count, followers_place, True)
        ),
        following=UserRankResponse(
            total=user.following_count,
            place=following_place,
            to_next=gap(next_following, user.following_count, following_place),
            to_top_100=gap(top_following, user.following_count, following_place, True)
        ),
        posts=UserRankResponse(
            total=user.posts_count,
            place=posts_place,
            to_next=gap(next_posts, user.posts_count, posts_place),
            to_top_100=gap(top_posts, user.posts_count, posts_place, True)
        )
    )


@router.post("/{id}/refresh", status_code=204)
@get_limiter().limit("5/minute")
def api_post_ebdi_users_refresh(
    request: Request, id: int, db: Session = Depends(get_db)
):
    user = db.query(User).where(User.id == id).first()
    if not user:
        return JSONResponse({"detail": "user not found"}, 404)
    return JSONResponse({"detail": "not implemented"}, 400)


@router.get("/search")
def api_get_ebdi_user_search(
    query: str,
    order: UserOrder = UserOrder.followers,
    descending: bool = True,
    db: Session = Depends(get_db)
):
    # поиск всегда идёт по всей базе без фильтров, поэтому position совпадает с нефильтрованным списком в выбранной сортировке
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    users_query, u = build_users_query(db, order, descending, None, None, None, None)
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


@router.get("/count")
def api_get_user_count(request: Request, db: Session = Depends(get_db)):
    if datetime.now() - request.app.state.users_count_updated_at > timedelta(hours=1):
        request.app.state.users_count = db.query(User).count()
        request.app.state.users_count_updated_at = datetime.now()
    return {"count": request.app.state.users_count}


@router.get("/graph")
def api_get_users_graph(request: Request, db: Session = Depends(get_db)):
    users = (
        db.query(
            User.id,
            User.user_id,
            User.username,
            User.display_name,
            User.followers_count,
            User.following_count,
            User.verified,
            User.avatar,
            User.following,
            User.followers
        )
        .where(or_(User.followers_count > 0, User.following_count > 0))
        .all()
    )
    user_ids = {str(user.user_id): user.id for user in users}

    edges: set[tuple[int, int]] = set()
    for user in users:
        for target in user.following + user.followers:
            target_id = user_ids.get(str(target))
            if target_id is not None and (target_id, user.id) not in edges:
                edges.add((user.id, target_id))

    linked_ids = {i for edge in edges for i in edge}
    users = [user for user in users if user.id in linked_ids]

    nodes = [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "followers": u.followers_count,
            "following": u.following_count,
            "verified": u.verified,
            "avatar": u.avatar
        }
        for u in users
    ]

    return Response(
        content=dumps(
            {"nodes": nodes, "edges": [{"source": s, "target": t} for s, t in edges]}
        ),
        media_type="application/json"
    )
