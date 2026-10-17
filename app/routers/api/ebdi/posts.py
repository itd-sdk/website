from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func
from sqlalchemy.orm import aliased

from app.schemas import Post, User
from app.services.db import Session, get_db
from app.services.limiter import get_limiter

router = APIRouter(prefix="/posts")


class PostSort(Enum):
    new = "new"  # by the time the post got into the database
    likes = "likes"
    reposts = "reposts"
    comments = "comments"
    views = "views"


class PostPeriod(Enum):
    all = "all"
    day = "day"
    week = "week"
    month = "month"


SORT_COLUMNS = {
    PostSort.new: Post.found_at,
    PostSort.likes: Post.likes_count,
    PostSort.reposts: Post.reposts_count,
    PostSort.comments: Post.comments_count,
    PostSort.views: Post.views_count
}
PERIODS = {
    PostPeriod.day: timedelta(days=1),
    PostPeriod.week: timedelta(days=7),
    PostPeriod.month: timedelta(days=30)
}


class PostAuthor(BaseModel):
    id: int
    user_id: UUID
    username: str
    display_name: str
    avatar: str
    verified: bool
    exists: bool


class PostResponse(BaseModel):
    post_id: UUID
    author_id: UUID
    author: PostAuthor | None  # None if the author is not in the database
    created_at: datetime | None
    edited_at: datetime | None
    found_at: datetime
    content: str
    attachments: list[str]
    likes_count: int
    comments_count: int
    reposts_count: int
    views_count: int
    poll_question: str | None
    poll_options: list[str] | None
    poll_multiple: bool | None
    dominant: str | None
    original_post_id: UUID | None
    wall_recipient_id: UUID | None
    wall_recipient: PostAuthor | None  # owner of the wall the post was left on
    exists: bool
    original: "PostResponse | None" = None  # the reposted post, if it is stored


def attachment_urls(attachments: list) -> list[str]:
    # posts scraped by older clients kept whole attachment objects
    return [
        a if isinstance(a, str) else a.get("url")
        for a in attachments
        if isinstance(a, str) or (isinstance(a, dict) and a.get("url"))
    ]


def to_author(user: User | None) -> PostAuthor | None:
    return PostAuthor.model_validate(user, from_attributes=True) if user else None


def to_response(
    post: Post,
    author: User | None,
    recipient: User | None,
    original: PostResponse | None = None
) -> PostResponse:
    return PostResponse(
        post_id=post.post_id,
        author_id=post.author_id,
        author=to_author(author),
        created_at=post.created_at,
        edited_at=post.edited_at,
        found_at=post.found_at,
        content=post.content,
        attachments=attachment_urls(post.attachments or []),
        likes_count=post.likes_count,
        comments_count=post.comments_count,
        reposts_count=post.reposts_count,
        views_count=post.views_count,
        poll_question=post.poll_question,
        poll_options=post.poll_options,
        poll_multiple=post.poll_multiple,
        dominant=post.dominant,
        original_post_id=post.original_post_id,
        wall_recipient_id=post.wall_recipient_id,
        wall_recipient=to_author(recipient)
        if post.wall_recipient_id != post.author_id
        else None,
        exists=post.exists,
        original=original
    )


def posts_with_users(db: Session):
    recipient = aliased(User)
    return (
        db.query(Post, User, recipient)
        .outerjoin(User, User.user_id == Post.author_id)
        .outerjoin(recipient, recipient.user_id == Post.wall_recipient_id)
    )


@router.get("", response_model=list[PostResponse])
@get_limiter().limit("30/minute")
def api_get_ebdi_posts(
    request: Request,
    sort: PostSort = PostSort.new,
    period: PostPeriod = PostPeriod.all,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db)
):
    query = posts_with_users(db)
    if period != PostPeriod.all:
        query = query.where(Post.created_at >= datetime.now() - PERIODS[period])
    rows = (
        query.order_by(desc(SORT_COLUMNS[sort]), desc(Post.id))
        .offset(offset)
        .limit(limit)
        .all()
    )

    # reposted posts of the whole page in one query
    original_ids = {post.original_post_id for post, _, _ in rows if post.original_post_id}
    originals = {}
    if original_ids:
        for post, author, recipient in posts_with_users(db).where(
            Post.post_id.in_(original_ids)
        ):
            originals[post.post_id] = to_response(post, author, recipient)

    return [
        to_response(post, author, recipient, originals.get(post.original_post_id))
        for post, author, recipient in rows
    ]


posts_count: int | None = None
posts_count_updated_at = datetime.min


@router.get("/count")
def api_get_ebdi_posts_count(db: Session = Depends(get_db)):
    global posts_count, posts_count_updated_at
    if datetime.now() - posts_count_updated_at > timedelta(hours=1):
        posts_count = db.query(func.count(Post.id)).scalar()
        posts_count_updated_at = datetime.now()
    return {"count": posts_count}
