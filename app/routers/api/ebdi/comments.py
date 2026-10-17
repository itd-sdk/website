from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import aliased

from app.routers.api.ebdi.posts import (
    PostAuthor,
    attachment_urls,
    ilike_pattern,
    matching_users,
    to_author
)
from app.schemas import Comment, Post, User
from app.services.db import Session, get_db
from app.services.limiter import get_limiter

router = APIRouter(prefix="/comments")


class CommentSort(Enum):
    created = "created"
    found = "found"  # by the time the comment got into the database
    likes = "likes"
    replies = "replies"


SORT_COLUMNS = {
    CommentSort.created: Comment.created_at,
    CommentSort.found: Comment.found_at,
    CommentSort.likes: Comment.likes_count,
    CommentSort.replies: Comment.replies_count
}


class CommentResponse(BaseModel):
    comment_id: UUID
    post_id: UUID
    parent_id: UUID | None  # set for replies
    author_id: UUID
    author: PostAuthor | None
    reply_to: PostAuthor | None  # user being replied to
    post_author: PostAuthor | None  # for the link to the post
    post_exists: bool
    created_at: datetime | None
    found_at: datetime
    content: str
    attachments: list[str]
    likes_count: int
    replies_count: int


def comments_with_users(db: Session):
    author = aliased(User)
    reply_to = aliased(User)
    post_author = aliased(User)
    return (
        db.query(Comment, Post.exists, author, reply_to, post_author)
        .join(Post, Post.post_id == Comment.post_id)
        .outerjoin(author, author.user_id == Comment.author_id)
        .outerjoin(reply_to, reply_to.user_id == Comment.reply_to_id)
        .outerjoin(post_author, post_author.user_id == Post.author_id)
    )


def to_response(row) -> CommentResponse:
    comment, post_exists, author, reply_to, post_author = row
    return CommentResponse(
        comment_id=comment.comment_id,
        post_id=comment.post_id,
        parent_id=comment.parent_id,
        author_id=comment.author_id,
        author=to_author(author),
        reply_to=to_author(reply_to),
        post_author=to_author(post_author),
        post_exists=post_exists,
        created_at=comment.created_at,
        found_at=comment.found_at,
        content=comment.content,
        attachments=attachment_urls(comment.attachments or []),
        likes_count=comment.likes_count,
        replies_count=comment.replies_count
    )


@router.get("", response_model=list[CommentResponse])
@get_limiter().limit("30/minute")
def api_get_ebdi_comments(
    request: Request,
    sort: CommentSort = CommentSort.found,
    q: str = Query("", max_length=200),  # text in the content
    user: str = Query("", max_length=100),  # text in the author's name
    deleted: bool = False,  # comments under deleted posts
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db)
):
    query = comments_with_users(db)
    if not deleted:
        query = query.where(Post.exists.is_(True))
    if q.strip():
        query = query.where(
            Comment.content.ilike(ilike_pattern(q.strip()), escape="\\")
        )
    if user.strip():
        query = query.where(Comment.author_id.in_(matching_users(user)))
    rows = (
        query.order_by(desc(SORT_COLUMNS[sort]).nulls_last(), desc(Comment.id))
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [to_response(row) for row in rows]


THREAD_BATCH = 100
REPLIES_PREVIEW = 3


class ThreadComment(CommentResponse):
    replies: list[CommentResponse]  # the first few replies
    replies_total: int  # stored replies, the rest are loaded on demand


def chronological(query):
    return query.order_by(Comment.created_at.asc().nulls_last(), Comment.id)


@router.get("/post/{post_id}", response_model=list[ThreadComment])
@get_limiter().limit("60/minute")
def api_get_ebdi_post_comments(
    request: Request,
    post_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(THREAD_BATCH, ge=1, le=THREAD_BATCH),
    db: Session = Depends(get_db)
):
    rows = (
        chronological(
            comments_with_users(db)
            .where(Comment.post_id == post_id)
            .where(Comment.parent_id.is_(None))
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    ids = [row[0].comment_id for row in rows]

    # first replies of every comment in one query
    ranked = (
        select(
            Comment.id,
            func.row_number()
            .over(
                partition_by=Comment.parent_id,
                order_by=(Comment.created_at.asc().nulls_last(), Comment.id)
            )
            .label("place"),
            func.count().over(partition_by=Comment.parent_id).label("total")
        )
        .where(Comment.parent_id.in_(ids))
        .subquery()
    )
    previews: dict[UUID, list[CommentResponse]] = {}
    totals: dict[UUID, int] = {}
    for *row, total in chronological(
        comments_with_users(db)
        .join(ranked, ranked.c.id == Comment.id)
        .where(ranked.c.place <= REPLIES_PREVIEW)
        .add_columns(ranked.c.total)
    ):
        reply = to_response(row)
        previews.setdefault(reply.parent_id, []).append(reply)
        totals[reply.parent_id] = total

    return [
        ThreadComment(
            **to_response(row).model_dump(),
            replies=previews.get(row[0].comment_id, []),
            replies_total=totals.get(row[0].comment_id, 0)
        )
        for row in rows
    ]


@router.get("/{comment_id}/replies", response_model=list[CommentResponse])
@get_limiter().limit("60/minute")
def api_get_ebdi_comment_replies(
    request: Request,
    comment_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(THREAD_BATCH, ge=1, le=THREAD_BATCH),
    db: Session = Depends(get_db)
):
    rows = (
        chronological(comments_with_users(db).where(Comment.parent_id == comment_id))
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [to_response(row) for row in rows]


comments_count: int | None = None
comments_count_updated_at = datetime.min


@router.get("/count")
def api_get_ebdi_comments_count(db: Session = Depends(get_db)):
    global comments_count, comments_count_updated_at
    if datetime.now() - comments_count_updated_at > timedelta(hours=1):
        comments_count = db.query(func.count(Comment.id)).scalar()
        comments_count_updated_at = datetime.now()
    return {"count": comments_count}
