from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import and_, case, desc, extract, func, literal, not_, text

from app.schemas import Comment, Post, User
from app.services.db import Session, get_db
from app.services.limiter import get_limiter

router = APIRouter(prefix="/stats")

# log-scale buckets, upper bound is exclusive
FOLLOWER_BUCKETS = [0, 1, 2, 10, 50, 100, 500, 1000, 5000]
RATIO_BUCKETS = [0, 0.1, 0.5, 1, 1.25, 1.5, 1.75, 2, 3, 5, 10]

IMPRECISE_CREATED_AT = and_(
    extract("day", User.created_at) == 1,
    extract("hour", User.created_at).in_([6, 7]),
    extract("minute", User.created_at) == 0,
    extract("second", User.created_at) == 0
)


def bucket_case(column, bounds: list):
    # assigns each row the lower bound of its bucket
    return case(
        *[(column < bounds[i + 1], literal(bounds[i])) for i in range(len(bounds) - 1)],
        else_=literal(bounds[-1])
    )


class Bucket(BaseModel):
    bucket: float
    count: int


class ScatterPoint(BaseModel):
    x: float
    y: float
    count: int = 1  # users in the cell


class TimePoint(BaseModel):
    x: datetime
    y: float
    count: int = 1


class ClanShare(BaseModel):
    clan: str
    points: list[TimePoint]


class Cohort(BaseModel):
    month: datetime
    total: int
    verified: int
    has_itdp: int
    deleted: int


class LastSeenShare(BaseModel):
    last_seen: str | None
    count: int


class Registrations(BaseModel):
    date: datetime
    count: int  # without month-only dates
    count_all: int  # everything


class Total(BaseModel):
    month: datetime
    total: int


def get_registrations(db: Session) -> list[Registrations]:
    day = func.date_trunc("day", User.created_at).label("day")
    rows = (
        db.query(
            day,
            func.count(User.id),
            func.count(User.id).filter(not_(IMPRECISE_CREATED_AT))
        )
        .where(User.created_at.isnot(None))
        .group_by("day")
        .order_by("day")
        .all()
    )
    return [
        Registrations(date=value, count=precise, count_all=total)
        for value, total, precise in rows
    ]


def get_total(db: Session) -> list[Total]:
    rows = (
        db.query(
            func.date_trunc("month", User.created_at).label("month"),
            func.count(User.id)
        )
        .where(User.created_at.isnot(None))
        .group_by("month")
        .order_by("month")
        .all()
    )
    result = []
    total = 0
    for value, count in rows:
        total += count
        result.append(Total(month=value, total=total))
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


# scatter charts get cells instead of users: an axis is cut into equal cells
# and every cell carries its users
GRID_CELLS = 100  # cells along an axis
MAX_FOLLOWERS = 2000
MAX_CELLS = 20000


def grid_cell(column, top: float):
    return func.floor(column / max(1.0, top / GRID_CELLS))


def get_followers_by_age(db: Session) -> list[TimePoint]:
    # days would put the points of neighbouring cells on top of each other
    week = func.date_trunc("week", User.created_at)
    rows = (
        db.query(week, func.avg(User.followers_count), func.count())
        .where(User.exists.is_(True))
        .where(User.created_at.isnot(None))
        .where(User.followers_count < MAX_FOLLOWERS)
        .where(not_(IMPRECISE_CREATED_AT))
        .group_by(week, grid_cell(User.followers_count, MAX_FOLLOWERS))
        .order_by(desc(func.count()))
        .limit(MAX_CELLS)
        .all()
    )
    return [
        TimePoint(x=created_at, y=followers, count=count)
        for created_at, followers, count in rows
    ]


def get_posts_vs_followers(db: Session) -> list[ScatterPoint]:
    def users(*columns):
        return (
            db.query(*columns)
            .where(User.exists.is_(True))
            .where(User.posts_count > 0)
            .where(User.followers_count < MAX_FOLLOWERS)
        )

    max_posts = users(func.max(User.posts_count)).scalar() or 0
    rows = (
        users(
            func.avg(User.posts_count), func.avg(User.followers_count), func.count()
        )
        .group_by(
            grid_cell(User.posts_count, max_posts),
            grid_cell(User.followers_count, MAX_FOLLOWERS)
        )
        .order_by(desc(func.count()))
        .limit(MAX_CELLS)
        .all()
    )
    return [
        ScatterPoint(x=posts, y=followers, count=count)
        for posts, followers, count in rows
    ]


def get_clans_over_time(db: Session) -> list[ClanShare]:
    top = [
        clan
        for (clan,) in db.query(User.avatar)
        .where(User.exists.is_(True))
        .where(User.avatar.isnot(None))
        .where(User.avatar != "")
        .group_by(User.avatar)
        .order_by(desc(func.count(User.id)))
        .limit(10)
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
        .where(not_(IMPRECISE_CREATED_AT))
        .group_by(User.avatar, "week")
        .order_by("week")
        .all()
    )

    counts: dict[str, dict[datetime, int]] = {clan: {} for clan in top}
    for clan, value, count in rows:
        counts[clan][value] = count

    weeks = sorted({value for _, value, _ in rows})
    if not weeks:
        return []

    grid = []
    current = weeks[0]
    while current <= weeks[-1]:
        grid.append(current)
        current += timedelta(weeks=1)

    return [
        ClanShare(
            clan=clan,
            points=[TimePoint(x=week, y=counts[clan].get(week, 0)) for week in grid]
        )
        for clan in top
    ]


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


def get_running_total(db: Session, created_at) -> list[Total]:
    rows = (
        db.query(func.date_trunc("month", created_at).label("month"), func.count())
        .where(created_at.isnot(None))
        .group_by("month")
        .order_by("month")
        .all()
    )
    result = []
    total = 0
    for value, count in rows:
        total += count
        result.append(Total(month=value, total=total))
    return result


class PerDay(BaseModel):
    date: datetime
    count: int


def get_per_day(db: Session, created_at) -> list[PerDay]:
    day = func.date_trunc("day", created_at).label("day")
    rows = (
        db.query(day, func.count())
        .where(created_at.isnot(None))
        .group_by("day")
        .order_by("day")
        .all()
    )
    return [PerDay(date=value, count=count) for value, count in rows]


class WordCount(BaseModel):
    word: str
    count: int


STOPWORDS = sorted(
    set(
        """
    без был была были было быть вам вас ведь весь вот все всё всего всех всем вообще
    где даже для его если есть еще ещё жду или как какой кого когда кто куда
    лишь между меня мне мной мое моё может можно мой моя надо нас него нее неё
    нет нибудь них ничего ну оба она они оно опять очень пока почему потом
    потому при про раз сам свой свою себе себя сейчас так такой там тебе тебя
    тем теперь то тоже только том тот три тут ты уже хоть хотя чего чем через
    что чтобы чтоб эта эти это этого этой этом этот эту будет будут буду была
    было вы мы он она где-то кстати вроде типа просто реально вообще прям
    чуть сколько свои своих своей нам ним ней них его ее её им их тех тот
    the and you for that this with are not but have was what all your can
    just from they will about like http https www com
""".split()
    )
)
WORDS_SQL = """
    select word, count(*) as count
    from (
        select regexp_split_to_table(
            translate(
                lower(regexp_replace(content, 'https?://\\S+|@\\w+', ' ', 'g')),
                'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ',
                'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
            ),
            '[^a-zа-яё]+'
        ) as word
        from {table}
        where content <> ''
    ) words
    where length(word) between 3 and 30 and word <> all(:stopwords)
    group by word
    order by count desc
    limit 120
"""


def get_top_words(db: Session, table: str) -> list[WordCount]:
    # uppercase cyrillic is mapped by hand, lower() depends on the database locale
    rows = db.execute(text(WORDS_SQL.format(table=table)), {"stopwords": STOPWORDS})
    return [WordCount(word=word, count=count) for word, count in rows]


class ClanCount(BaseModel):
    clan: str
    count: int


def get_post_captures(db: Session) -> list[ClanCount]:
    # emoji may come with or without the variation selector
    clan = func.replace(Post.dominant, "\ufe0f", "")
    rows = (
        db.query(clan, func.count())
        .where(Post.exists.is_(True))
        .where(Post.dominant.is_not(None))
        .where(Post.dominant != "")
        .group_by(clan)
        .order_by(desc(func.count()))
        .limit(10)
    )
    return [ClanCount(clan=clan, count=count) for clan, count in rows]


class StatsResponse(BaseModel):
    total: list[Total]
    registrations: list[Registrations]
    followers_distribution: list[Bucket]
    followers_by_age: list[TimePoint]
    posts_vs_followers: list[ScatterPoint]
    clans_over_time: list[ClanShare]
    last_seen: list[LastSeenShare]
    cohorts: list[Cohort]
    follow_ratio: list[Bucket]
    posts_total: list[Total]
    posts_per_day: list[PerDay]
    comments_total: list[Total]
    comments_per_day: list[PerDay]
    words_posts: list[WordCount]
    words_comments: list[WordCount]
    post_captures: list[ClanCount]  # posts each clan holds as the dominant one


@router.get("/", response_model=StatsResponse)
@get_limiter().limit("10/minute")
def api_get_ebdi_stats(request: Request, db: Session = Depends(get_db)):
    if datetime.now() - request.app.state.stats_updated_at > timedelta(hours=6):
        request.app.state.stats = StatsResponse(
            total=get_total(db),
            registrations=get_registrations(db),
            followers_distribution=get_followers_distribution(db),
            followers_by_age=get_followers_by_age(db),
            posts_vs_followers=get_posts_vs_followers(db),
            clans_over_time=get_clans_over_time(db),
            last_seen=get_last_seen(db),
            cohorts=get_cohorts(db),
            follow_ratio=get_follow_ratio(db),
            posts_total=get_running_total(db, Post.created_at),
            posts_per_day=get_per_day(db, Post.created_at),
            comments_total=get_running_total(db, Comment.created_at),
            comments_per_day=get_per_day(db, Comment.created_at),
            words_posts=get_top_words(db, "posts"),
            words_comments=get_top_words(db, "comments"),
            post_captures=get_post_captures(db)
        ).model_dump_json()
        request.app.state.stats_updated_at = datetime.now()
    return Response(content=request.app.state.stats, media_type="application/json")
