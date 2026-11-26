"""How much of итд the database holds.

итд does not publish its totals, but it does publish the member counts of its
biggest clans and the post counts of its trending hashtags. The same clans and
hashtags are counted in the database, the ratio is the estimated share.
"""

from datetime import datetime, timedelta
from threading import Lock

from fastapi import APIRouter, Depends, Request
from itd import Hashtags, TopClans
from pydantic import BaseModel
from sqlalchemy import func

from app.logger import get_logger
from app.routers.api.ebdi.hashtags import get_counts
from app.schemas import User
from app.services.db import Session, get_db
from app.services.limiter import get_limiter

router = APIRouter(prefix="/coverage")
l = get_logger("ebdi.coverage")

CACHE_TTL = timedelta(hours=6)
RETRY_TTL = timedelta(minutes=10)  # after a failed request to итд
TRENDING_HASHTAGS = 20


class Share(BaseModel):
    share: float  # ours / official
    ours: int
    official: int
    sample: int  # clans or hashtags compared


class CoverageResponse(BaseModel):
    users: Share | None  # None when итд could not be asked
    posts: Share | None


def normalize_emoji(value: str) -> str:
    return value.replace("︎", "").replace("️", "")


def users_share(db: Session) -> Share:
    clans = {normalize_emoji(clan.avatar): clan.members_count for clan in TopClans()}
    ours = dict(
        db.query(User.avatar, func.count(User.id))
        .where(User.exists.is_(True))
        .where(User.avatar.in_(list(clans)))
        .group_by(User.avatar)
        .all()
    )
    official = sum(clans.values())
    if not official:
        raise ValueError("итд returned no counts")
    counted = sum(ours.get(clan, 0) for clan in clans)
    return Share(
        share=counted / official, ours=counted, official=official, sample=len(clans)
    )


def posts_share(db: Session) -> Share:
    hashtags = {
        tag.name.lower(): tag.posts_count for tag in Hashtags(limit=TRENDING_HASHTAGS)
    }
    ours = get_counts(db)["posts"]
    official = sum(hashtags.values())
    if not official:
        raise ValueError("итд returned no counts")
    counted = sum(ours.get(tag, 0) for tag in hashtags)
    return Share(
        share=counted / official, ours=counted, official=official, sample=len(hashtags)
    )


cache: CoverageResponse | None = None
cache_expires_at = datetime.min
# the hashtag count is heavy, parallel first requests wait for one of them
lock = Lock()


def compute(db: Session) -> tuple[CoverageResponse, timedelta]:
    shares = {}
    ttl = CACHE_TTL
    for name, count in (("users", users_share), ("posts", posts_share)):
        try:
            shares[name] = count(db)
        except Exception as error:
            l.warning("coverage of %s failed: %r", name, error)
            shares[name] = None
            ttl = RETRY_TTL
    return CoverageResponse(**shares), ttl


@router.get("", response_model=CoverageResponse)
@get_limiter().limit("30/minute")
def api_get_ebdi_coverage(request: Request, db: Session = Depends(get_db)):
    global cache, cache_expires_at
    with lock:
        if cache is None or datetime.now() > cache_expires_at:
            cache, ttl = compute(db)
            cache_expires_at = datetime.now() + ttl
        return cache
