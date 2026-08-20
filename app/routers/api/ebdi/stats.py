from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import case, desc, func, literal

from app.schemas import User
from app.services.db import Session, get_db
from app.services.limiter import get_limiter

router = APIRouter(prefix="/stats")

# log-scale buckets, upper bound is exclusive
FOLLOWER_BUCKETS = [0, 1, 2, 10, 50, 100, 500, 1000, 5000]
RATIO_BUCKETS = [0, 0.1, 0.5, 1, 2, 5, 10]


def bucket_case(column, bounds: list):
    # assigns each row the lower bound of its bucket
    return case(
        *[(column < bounds[i + 1], literal(bounds[i])) for i in range(len(bounds) - 1)],
        else_=literal(bounds[-1])
    )


class Registrations(BaseModel):
    month: datetime
    count: int
    total: int


class Bucket(BaseModel):
    bucket: float
    count: int


class ScatterPoint(BaseModel):
    x: datetime
    y: float


class ClanShare(BaseModel):
    clan: str
    points: list[ScatterPoint]


class Cohort(BaseModel):
    month: datetime
    total: int
    verified: int
    has_itdp: int
    deleted: int


class LastSeenShare(BaseModel):
    last_seen: str | None
    count: int


def get_registrations(db: Session) -> list[Registrations]:
    rows = (
        db.query(
            func.date_trunc("week", User.created_at).label("week"), func.count(User.id)
        )
        .where(User.created_at.isnot(None))
        .group_by("week")
        .order_by("week")
        .all()
    )
    total = 0
    result = []
    for value, count in rows:
        total += count
        result.append(Registrations(month=value, count=count, total=total))
    return result


def get_followers_distribution(db: Session) -> list[Bucket]:
    bucket = bucket_case(User.followers_count, FOLLOWER_BUCKETS).label("bucket")
    rows = (
        db.query(bucket, func.count(User.id))
        .where(User.exists.is_(True))
        .group_by("bucket")
        .order_by("bucket")
        .all()
    )
    return [Bucket(bucket=value, count=count) for value, count in rows]


def get_followers_by_age(db: Session) -> list[ScatterPoint]:
    # sampling keeps the payload small enough to render client side
    rows = (
        db.query(User.created_at, User.followers_count)
        .where(User.exists.is_(True))
        .where(User.created_at.isnot(None))
        .order_by(desc(User.followers_count))
        .limit(5000)
        .all()
    )
    return [
        ScatterPoint(x=created_at.timestamp() * 1000, y=followers)
        for created_at, followers in rows
    ]


def get_posts_vs_followers(db: Session) -> list[ScatterPoint]:
    rows = (
        db.query(User.posts_count, User.followers_count)
        .where(User.exists.is_(True))
        .where(User.posts_count > 0)
        .order_by(desc(User.followers_count))
        .limit(5000)
        .all()
    )
    return [ScatterPoint(x=posts, y=followers) for posts, followers in rows]


def get_clans_over_time(db: Session) -> list[ClanShare]:
    top = [
        clan
        for (clan,) in db.query(User.avatar)
        .where(User.exists.is_(True))
        .where(User.avatar.isnot(None))
        .where(User.avatar != "")
        .group_by(User.avatar)
        .order_by(desc(func.count(User.id)))
        .limit(8)
        .all()
    ]
    if not top:
        return []

    rows = (
        db.query(
            User.avatar,
            func.date_trunc("week", User.created_at).label("week"),
            func.count(User.id)
        )
        .where(User.avatar.in_(top))
        .where(User.created_at.isnot(None))
        .group_by(User.avatar, "week")
        .order_by("week")
        .all()
    )
    shares: dict[str, list[ScatterPoint]] = {clan: [] for clan in top}
    for clan, value, count in rows:
        shares[clan].append(ScatterPoint(x=value, y=count))
    return [ClanShare(clan=clan, points=points) for clan, points in shares.items()]


def get_last_seen(db: Session) -> list[LastSeenShare]:
    rows = (
        db.query(User.last_seen, func.count(User.id))
        .where(User.exists.is_(True))
        .group_by(User.last_seen)
        .order_by(desc(func.count(User.id)))
        .all()
    )
    rows = {value: count for value, count in rows}
    return [
        LastSeenShare(last_seen=None, count=rows[None]),
        LastSeenShare(
            last_seen="На этой неделе",
            count=rows.get("recently", 0)
            + rows.get("just_now", 0)
            + rows.get("this_week", 0)
        ),
        LastSeenShare(last_seen="В этом месяце", count=rows.get("this_month", 0)),
        LastSeenShare(last_seen="Давно", count=rows.get("long_ago", 0))
    ]


def get_cohorts(db: Session) -> list[Cohort]:
    rows = (
        db.query(
            func.date_trunc("month", User.created_at).label("month"),
            func.count(User.id),
            func.count(User.id).filter(User.verified.is_(True)),
            func.count(User.id).filter(User.has_itdp.is_(True)),
            func.count(User.id).filter(User.exists.is_(False))
        )
        .where(User.created_at.isnot(None))
        .group_by("month")
        .order_by("month")
        .all()
    )
    cohorts = []
    total_users = 0
    total_verified = 0
    total_itdp = 0
    total_deleted = 0
    for value, total, verified, has_itdp, deleted in rows:
        total_users += total
        total_verified += verified
        total_itdp += has_itdp
        total_deleted += deleted
        cohorts.append(
            Cohort(
                month=value,
                total=total_users,
                verified=total_verified,
                has_itdp=total_itdp,
                deleted=total_deleted
            )
        )
    return cohorts


def get_follow_ratio(db: Session) -> list[Bucket]:
    # guard against division by zero for users with no followers
    ratio = User.following_count / func.greatest(User.followers_count, 1)
    bucket = bucket_case(ratio, RATIO_BUCKETS).label("bucket")
    rows = (
        db.query(bucket, func.count(User.id))
        .where(User.exists.is_(True))
        .where(User.following_count > 0)
        .group_by("bucket")
        .order_by("bucket")
        .all()
    )
    return [Bucket(bucket=value, count=count) for value, count in rows]


class StatsResponse(BaseModel):
    registrations: list[Registrations]
    followers_distribution: list[Bucket]
    followers_by_age: list[ScatterPoint]
    posts_vs_followers: list[ScatterPoint]
    clans_over_time: list[ClanShare]
    last_seen: list[LastSeenShare]
    cohorts: list[Cohort]
    follow_ratio: list[Bucket]


@router.get("/", response_model=StatsResponse)
@get_limiter().limit("10/minute")
def api_get_ebdi_stats(request: Request, db: Session = Depends(get_db)):
    if datetime.now() - request.app.state.stats_updated_at > timedelta(hours=6):
        request.app.state.stats = StatsResponse(
            registrations=get_registrations(db),
            followers_distribution=get_followers_distribution(db),
            followers_by_age=get_followers_by_age(db),
            posts_vs_followers=get_posts_vs_followers(db),
            clans_over_time=get_clans_over_time(db),
            last_seen=get_last_seen(db),
            cohorts=get_cohorts(db),
            follow_ratio=get_follow_ratio(db)
        ).model_dump_json()
        request.app.state.stats_updated_at = datetime.now()
    return Response(content=request.app.state.stats, media_type="application/json")
