from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import aliased

from app.routers.api.ebdi.posts import (
    PostAuthor,
    attachment_filter,
    ilike_pattern,
    matching_users,
    random_order,
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
    random = "random"


SORT_COLUMNS = {
    CommentSort.created: Comment.created_at,
    CommentSort.found: Comment.found_at,
    CommentSort.likes: Comment.likes_count,
    CommentSort.replies: Comment.replies_count
}


PREVIEW_LENGTH = 250


class Preview(BaseModel):
    """Short view of the post or the parent comment a comment belongs to"""

    author_id: UUID
    author: PostAuthor | None  # None if the author is not in the database
    content: str  # first PREVIEW_LENGTH characters
    truncated: bool


class CommentResponse(BaseModel):
    comment_id: UUID
    post_id: UUID
    parent_id: UUID | None  # set for replies
    author_id: UUID
    author: PostAuthor | None
    reply_to_id: UUID | None
    reply_to: PostAuthor | None  # user being replied to
    post_author: PostAuthor | None  # for the link to the post
    post_exists: bool
    exists: bool
    created_at: datetime | None
    found_at: datetime
    content: str
    attachments: list[str]
    likes_count: int
    replies_count: int
    post_preview: Preview | None = None  # only in the comments feed
    parent_preview: Preview | None = None


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
        reply_to_id=comment.reply_to_id,
        reply_to=to_author(reply_to),
        post_author=to_author(post_author),
        post_exists=post_exists,
        exists=comment.exists,
        created_at=comment.created_at,
        found_at=comment.found_at,
        content=comment.content,
        attachments=comment.attachments or [],
        likes_count=comment.likes_count,
        replies_count=comment.replies_count
    )


@router.get("", response_model=list[CommentResponse])
@get_limiter().limit("30/minute")
def api_get_ebdi_comments(
    request: Request,
    sort: CommentSort = CommentSort.found,
    q: str = Query("", max_length=200),  # text in the content
    user: str = Query("", max_length=100),  # author's username
    deleted: bool = False,  # deleted comments
    deleted_posts: bool = False,  # comments under deleted posts
    replies: bool = True,
    text: bool = True,  # comments without attachments
    photo: bool = True,  # comments with attachments of these kinds
    video: bool = True,
    audio: bool = True,
    seed: str = Query("", max_length=32),  # shuffle of the random sort
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db)
):
    query = comments_with_users(db)
    if not deleted:
        query = query.where(Comment.exists.is_(True))
    if not deleted_posts:
        query = query.where(Post.exists.is_(True))
    if not replies:
        query = query.where(Comment.parent_id.is_(None))
    for condition in attachment_filter(
        Comment.attachments, text, photo, video, audio
    ):
        query = query.where(condition)
    if q.strip():
        query = query.where(
            Comment.content.ilike(ilike_pattern(q.strip()), escape="\\")
        )
    if user.strip():
        query = query.where(Comment.author_id.in_(matching_users(user)))
    rows = (
        query.order_by(
            *(
                (random_order(Comment.comment_id, seed), Comment.id)
                if sort == CommentSort.random
                else (desc(SORT_COLUMNS[sort]).nulls_last(), desc(Comment.id))
            )
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    comments = [to_response(row) for row in rows]
    add_previews(db, comments)
    return comments


def previews(db: Session, model: type[Post] | type[Comment], key, ids: set[UUID]):
    if not ids:
        return {}
    rows = (
        db.query(
            key,
            model.author_id,
            func.left(model.content, PREVIEW_LENGTH),
            func.length(model.content) > PREVIEW_LENGTH,
            User
        )
        .outerjoin(User, User.user_id == model.author_id)
        .where(key.in_(ids))
    )
    return {
        id: Preview(
            author_id=author_id,
            author=to_author(author),
            content=content,
            truncated=truncated
        )
        for id, author_id, content, truncated, author in rows
    }


def add_previews(db: Session, comments: list[CommentResponse]) -> None:
    # previews of the whole page in two queries
    posts = previews(db, Post, Post.post_id, {c.post_id for c in comments})
    parents = previews(
        db, Comment, Comment.comment_id, {c.parent_id for c in comments if c.parent_id}
    )
    for comment in comments:
        comment.post_preview = posts.get(comment.post_id)
        if comment.parent_id:
            comment.parent_preview = parents.get(comment.parent_id)


THREAD_BATCH = 100
REPLIES_PREVIEW = 3


class ThreadComment(CommentResponse):
    replies: list[CommentResponse]  # the first few replies
    replies_total: int  # stored replies, the rest are loaded on demand


def chronological(query):
    return query.order_by(Comment.created_at.asc().nulls_last(), Comment.id)


class ThreadSort(Enum):
    """Order of the top-level comments in the post dialog"""

    new = "new"
    likes = "likes"
    replies = "replies"


THREAD_COLUMNS = {
    ThreadSort.new: Comment.created_at,
    ThreadSort.likes: Comment.likes_count,
    ThreadSort.replies: Comment.replies_count
}


def thread_order(sort: ThreadSort) -> tuple:
    return THREAD_COLUMNS[sort].desc().nulls_last(), Comment.id.desc()


def placed_before(sort: ThreadSort, comment: Comment):
    """Condition for the comments thread_order puts before this one"""
    column = THREAD_COLUMNS[sort]
    value = getattr(comment, column.key)
    if value is None:
        return or_(
            column.is_not(None), and_(column.is_(None), Comment.id > comment.id)
        )
    return or_(column > value, and_(column == value, Comment.id > comment.id))


@router.get("/post/{post_id}", response_model=list[ThreadComment])
@get_limiter().limit("60/minute")
def api_get_ebdi_post_comments(
    request: Request,
    post_id: UUID,
    sort: ThreadSort = ThreadSort.new,
    offset: int = Query(0, ge=0),
    limit: int = Query(THREAD_BATCH, ge=1, le=THREAD_BATCH),
    db: Session = Depends(get_db)
):
    rows = (
        comments_with_users(db)
        .where(Comment.post_id == post_id)
        .where(Comment.parent_id.is_(None))
        .order_by(*thread_order(sort))
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
        assert reply.parent_id
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


class CommentPlace(BaseModel):
    post_id: UUID
    comment_id: UUID  # top-level comment of the thread
    offset: int  # its index among the top-level comments of the post


@router.get("/{comment_id}/place", response_model=CommentPlace)
@get_limiter().limit("60/minute")
def api_get_ebdi_comment_place(
    request: Request,
    comment_id: UUID,
    sort: ThreadSort = ThreadSort.new,
    db: Session = Depends(get_db)
):
    comment = db.query(Comment).where(Comment.comment_id == comment_id).first()
    if comment is not None and comment.parent_id:
        comment = (
            db.query(Comment).where(Comment.comment_id == comment.parent_id).first()
        )
    if comment is None:
        raise HTTPException(404, "comment not found")

    offset = (
        db.query(func.count(Comment.id))
        .where(Comment.post_id == comment.post_id)
        .where(Comment.parent_id.is_(None))
        .where(placed_before(sort, comment))
        .scalar()
    )
    return CommentPlace(
        post_id=comment.post_id, comment_id=comment.comment_id, offset=offset
    )


comments_count: int | None = None
comments_count_updated_at = datetime.min


@router.get("/count")
def api_get_ebdi_comments_count(db: Session = Depends(get_db)):
    global comments_count, comments_count_updated_at
    if datetime.now() - comments_count_updated_at > timedelta(hours=1):
        comments_count = db.query(func.count(Comment.id)).scalar()
        comments_count_updated_at = datetime.now()
    return {"count": comments_count}
