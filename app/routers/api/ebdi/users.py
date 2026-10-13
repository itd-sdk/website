from datetime import datetime, timedelta
from enum import Enum
from json import dumps
from time import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from itd import User as ItdUser
from itd.exceptions import NotFoundError, TargetUserBannedError
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, or_

from app.routers.api.ebdi.protocol import NewUserBody
from app.schemas import User, UserSnapshot
from app.services.db import Session, get_db
from app.services.history import record_changes, user_state
from app.services.limiter import get_limiter

router = APIRouter(prefix="/users")


class UserResponse(NewUserBody):
    id: int
    user_id: UUID
    found_at: datetime
    updated_at: datetime | None = None
    has_itdp: bool
    exists: bool
    position: int = 0
    rank: int | None = None


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


def apply_filters(query, clan, verified, has_itdp, exists):
    if clan:
        query = query.where(User.avatar == clan)
    if verified is not None:
        query = query.where(User.verified == verified)
    if has_itdp is not None:
        query = query.where(User.has_itdp == has_itdp)
    if exists is not None:
        query = query.where(User.exists == exists)
    return query


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
    query = apply_filters(db.query(User), clan, verified, has_itdp, exists)
    return query.order_by(desc(col) if descending else col.asc(), User.id)


def rank_users(
    db: Session,
    users: list[User],
    order: UserOrder,
    descending: bool,
    offset: int,
    clan: str | None = None,
    verified: bool | None = None,
    has_itdp: bool | None = None,
    exists: bool | None = None
) -> list[UserResponse]:
    col = getattr(User, order.value)
    first = users[0]
    value = getattr(first, order.value)
    # rows ahead of the batch, ties broken by id to match the ordering
    ahead = col > value if descending else col < value
    base = (
        apply_filters(
            db.query(func.count(User.id)).where(User.exists.is_(True)),
            clan,
            verified,
            has_itdp,
            exists
        )
        .where(or_(ahead, and_(col == value, User.id < first.id)))
        .scalar()
    )

    result = []
    rank = base + 1
    for i, user in enumerate(users):
        response = UserResponse.model_validate(user, from_attributes=True)
        response.position = offset + i + 1
        if user.exists:
            response.rank = rank
            rank += 1
        result.append(response)
    return result


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
    start = time()
    query = build_users_query(db, order, descending, clan, verified, has_itdp, exists)
    users = query.offset(offset).limit(100).all()
    if not users:
        return []

    res = rank_users(
        db, users, order, descending, offset, clan, verified, has_itdp, exists
    )
    print(time() - start)
    return res


@router.get("/{id}/ranks")
@get_limiter().limit("20/minute")
def api_get_ebdi_user_ranks(request: Request, id: int, db: Session = Depends(get_db)):
    start = time()
    user = db.query(User).where(User.id == id).first()
    if user is None:
        raise HTTPException(detail="not found", status_code=404)

    if not user.exists:
        return UserRanksResponse(
            followers=UserRankResponse(total=user.followers_count),
            following=UserRankResponse(total=user.following_count),
            posts=UserRankResponse(total=user.posts_count)
        )

    def rank_for(column, value: int) -> UserRankResponse:
        # ties broken by id to match the list ordering
        ahead = (
            db.query(func.count(User.id))
            .where(User.exists.is_(True))
            .where(or_(column > value, and_(column == value, User.id < id)))
            .scalar()
        )
        next_value = (
            db.query(func.min(column))
            .where(User.exists.is_(True))
            .where(column > value)
            .scalar()
        )
        place = ahead + 1
        top_100 = None
        if place > 100:
            top_100 = (
                db.query(column)
                .where(User.exists.is_(True))
                .order_by(column.desc(), User.id)
                .offset(99)
                .limit(1)
                .scalar()
            )
        return UserRankResponse(
            total=value,
            place=place,
            to_next=(next_value - value) if next_value is not None else None,
            to_top_100=(top_100 - value) if top_100 is not None else None
        )

    print(time() - start)

    return UserRanksResponse(
        followers=rank_for(User.followers_count, user.followers_count),
        following=rank_for(User.following_count, user.following_count),
        posts=rank_for(User.posts_count, user.posts_count)
    )


@router.post("/{id}/refresh")
@get_limiter().limit("5/minute")
def api_post_ebdi_users_refresh(
    request: Request, id: int, db: Session = Depends(get_db)
):
    db_user = db.query(User).where(User.id == id).first()
    if not db_user:
        return JSONResponse({"detail": "user not found"}, 404)

    before = user_state(db_user)
    try:
        user = ItdUser(db_user.user_id)
        for i in NewUserBody.model_fields:
            if i in ("followers", "following", "created_at", "avatar"):
                continue
            if i == "last_seen" and user.last_seen:
                db_user.last_seen = user.last_seen.unit.value
            elif i == "user_id":
                db_user.user_id = user.id
            else:
                setattr(db_user, i, getattr(user, i))
    except (NotFoundError, TargetUserBannedError):
        db_user.exists = False
    else:
        db_user.exists = True
    finally:
        now = datetime.now()
        db_user.updated_at = now
        record_changes(db, db_user, before, now)
        db.commit()
    return UserResponse.model_validate(db_user, from_attributes=True)


class HistoryPoint(BaseModel):
    t: datetime
    followers: int
    following: int
    posts: int
    exists: bool


class HistoryResponse(BaseModel):
    points: list[HistoryPoint]
    # last time the user was seen existing and the first time it was gone
    deleted_between: tuple[datetime | None, datetime] | None = None


@router.get("/{id}/history", response_model=HistoryResponse)
@get_limiter().limit("20/minute")
def api_get_ebdi_user_history(
    request: Request, id: int, db: Session = Depends(get_db)
):
    user = db.query(User).where(User.id == id).first()
    if not user:
        return JSONResponse({"detail": "user not found"}, 404)

    points = [
        HistoryPoint(
            t=s.recorded_at,
            followers=s.followers_count,
            following=s.following_count,
            posts=s.posts_count,
            exists=s.exists
        )
        for s in db.query(UserSnapshot)
        .where(UserSnapshot.user_id == user.user_id)
        .order_by(UserSnapshot.recorded_at)
    ]
    # the current state is the last known point even if it was never snapshotted
    if not points or points[-1].t < user.updated_at:
        points.append(
            HistoryPoint(
                t=user.updated_at,
                followers=user.followers_count,
                following=user.following_count,
                posts=user.posts_count,
                exists=user.exists
            )
        )

    deleted_between = None
    if not user.exists:
        alive = [point.t for point in points if point.exists]
        last_alive = alive[-1] if alive else None
        first_gone = next(
            (
                point.t
                for point in points
                if not point.exists and (last_alive is None or point.t > last_alive)
            ),
            user.updated_at
        )
        deleted_between = (last_alive, first_gone)
    return HistoryResponse(points=points, deleted_between=deleted_between)


@router.get("/search")
def api_get_ebdi_user_search(
    query: str,
    order: UserOrder = UserOrder.followers,
    descending: bool = True,
    db: Session = Depends(get_db)
):
    pattern = f"%{query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%"
    col = getattr(User, order.value)
    users = (
        db.query(User)
        .where(
            or_(
                User.username.ilike(pattern, escape="\\"),
                User.display_name.ilike(pattern, escape="\\")
            )
        )
        .order_by(desc(col) if descending else col.asc(), User.id)
        .limit(20)
        .all()
    )

    result = []
    for user in users:
        value = getattr(user, order.value)
        ahead = col > value if descending else col < value
        # search results are scattered across the list, each needs its own count
        condition = or_(ahead, and_(col == value, User.id < user.id))
        response = UserResponse.model_validate(user, from_attributes=True)
        response.position = db.query(func.count(User.id)).where(condition).scalar() + 1
        if user.exists:
            response.rank = (
                db.query(func.count(User.id))
                .where(User.exists.is_(True))
                .where(condition)
                .scalar()
                + 1
            )
        result.append(response)
    return {"results": result}


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
