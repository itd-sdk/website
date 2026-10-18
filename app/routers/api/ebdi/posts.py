from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from itd.enums import ALL
from itd import Post as ItdPost
from itd.exceptions import NotFoundError, TargetUserBannedError
from pydantic import BaseModel
from sqlalchemy import desc, exists, false, func, or_, select
from sqlalchemy.orm import aliased

from app.logger import get_logger
from app.routers.api.ebdi.protocol import CommentBody
from app.routers.api.ebdi.storage import save_comments
from app.schemas import Post, User
from app.services.db import Session, get_db
from app.services.limiter import get_limiter

router = APIRouter(prefix="/posts")
l = get_logger("ebdi.posts")


class PostSort(Enum):
    created = "created"
    found = "found"  # by the time the post got into the database
    likes = "likes"
    comments = "comments"
    reposts = "reposts"
    views = "views"


SORT_COLUMNS = {
    PostSort.created: Post.created_at,
    PostSort.found: Post.found_at,
    PostSort.likes: Post.likes_count,
    PostSort.comments: Post.comments_count,
    PostSort.reposts: Post.reposts_count,
    PostSort.views: Post.views_count
}


def ilike_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# attachments are urls, their kind is told by the extension like on the page
ATTACHMENT_KINDS = {
    "photo": r"\.(jpe?g|png|gif|webp|avif)(\?|$)",
    "video": r"\.(mp4|webm|mov|m4v)(\?|$)",
    "audio": r"\.(ogg|oga|opus|wav|mp3|m4a|aac|flac)(\?|$)"
}


def has_attachment(column, kind: str):
    urls = func.jsonb_array_elements_text(column).table_valued("value")
    return exists(
        select(1)
        .select_from(urls)
        .where(urls.c.value.regexp_match(ATTACHMENT_KINDS[kind], "i"))
    )


def attachment_filter(
    column, text: bool, photo: bool, video: bool, audio: bool
) -> list:
    """Conditions hiding items with attachments of the unchecked kinds;
    an item without a recognized attachment counts as text, some stored
    attachment lists hold strings that are not links"""
    shown = {"photo": photo, "video": video, "audio": audio}
    if not text and not any(shown.values()):
        return [false()]
    conditions = [~has_attachment(column, kind) for kind, on in shown.items() if not on]
    if not text:
        conditions.append(or_(*(has_attachment(column, kind) for kind in shown)))
    return conditions


def matching_users(username: str):
    """user_id of users with this username, deleted accounts may share it"""
    return select(User.user_id).where(
        User.username == username.strip().removeprefix("@")
    )


class PostAuthor(BaseModel):
    id: int
    user_id: UUID
    username: str
    display_name: str
    avatar: str
    verified: bool
    exists: bool


class RedPen(BaseModel):
    """Word struck out and replaced, offsets are utf-16 like in javascript"""

    start: int
    end: int
    replacement: str
    created_at: datetime | None = None


class Corrector(BaseModel):
    """Word painted over"""

    start: int
    end: int
    created_at: datetime | None = None


def event_marks(model: type[RedPen] | type[Corrector], marks: list | None) -> list:
    # ids and actors stay on the server, the page needs only the ranges
    return [model.model_validate(mark) for mark in marks or []]


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
    red_pens: list[RedPen]
    correctors: list[Corrector]
    original: "PostResponse | None" = None  # the reposted post, if it is stored


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
        attachments=post.attachments or [],
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
        red_pens=event_marks(RedPen, post.red_pens),
        correctors=event_marks(Corrector, post.correctors),
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
    sort: PostSort = PostSort.found,
    q: str = Query("", max_length=200),  # text in the content
    user: str = Query("", max_length=100),  # author's username
    deleted: bool = False,
    text: bool = True,  # posts without attachments
    photo: bool = True,  # posts with attachments of these kinds
    video: bool = True,
    audio: bool = True,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db)
):
    query = posts_with_users(db)
    if not deleted:
        query = query.where(Post.exists.is_(True))
    for condition in attachment_filter(Post.attachments, text, photo, video, audio):
        query = query.where(condition)
    if q.strip():
        query = query.where(Post.content.ilike(ilike_pattern(q.strip()), escape="\\"))
    if user.strip():
        query = query.where(Post.author_id.in_(matching_users(user)))
    rows = (
        query.order_by(desc(SORT_COLUMNS[sort]).nulls_last(), desc(Post.id))
        .offset(offset)
        .limit(limit)
        .all()
    )

    # reposted posts of the whole page in one query
    original_ids = {
        post.original_post_id for post, _, _ in rows if post.original_post_id
    }
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


def get_post_response(db: Session, post_id: UUID) -> PostResponse:
    row = posts_with_users(db).where(Post.post_id == post_id).first()
    if row is None:
        raise HTTPException(404, "post not found")
    post, author, recipient = row
    original = None
    if post.original_post_id:
        found = (
            posts_with_users(db).where(Post.post_id == post.original_post_id).first()
        )
        if found:
            original = to_response(*found)
    return to_response(post, author, recipient, original)


@router.get("/{post_id}", response_model=PostResponse)
@get_limiter().limit("60/minute")
def api_get_ebdi_post(request: Request, post_id: UUID, db: Session = Depends(get_db)):
    return get_post_response(db, post_id)


def to_comment_body(comment, replies: list[CommentBody]) -> CommentBody:
    return CommentBody(
        comment_id=comment.id,
        author_id=comment.author.id,
        reply_to_id=comment.reply_to.id if comment.reply_to else None,
        created_at=comment.created_at,
        content=comment.content,
        attachments=[attachment.url for attachment in comment.attachments],
        likes_count=comment.likes_count,
        replies_count=comment.replies_count,
        replies=replies
    )


def fetch_comment_tree(itd_post) -> list[CommentBody]:
    itd_post.comments.load(ALL)
    tree = []
    for comment in itd_post.comments:
        replies = list(comment.first_replies)
        if comment.replies_count > len(replies):
            comment.replies.load(ALL)
            replies = list(comment.replies)
        tree.append(to_comment_body(comment, [to_comment_body(r, []) for r in replies]))
    return tree


@router.post("/{post_id}/refresh", response_model=PostResponse)
@get_limiter().limit("5/minute")
def api_post_ebdi_post_refresh(
    request: Request, post_id: UUID, db: Session = Depends(get_db)
):
    post = db.query(Post).where(Post.post_id == post_id).first()
    if post is None:
        raise HTTPException(404, "post not found")

    try:
        itd_post = ItdPost(post_id)
        comments_changed = itd_post.comments_count != post.comments_count
        post.likes_count = itd_post.likes_count
        post.comments_count = itd_post.comments_count
        post.reposts_count = itd_post.reposts_count
        post.views_count = itd_post.views_count
        post.content = itd_post.content
        post.edited_at = itd_post.edited_at
        post.dominant = itd_post.dominant
        post.attachments = [attachment.url for attachment in itd_post.attachments]
        # same shape as the scraper stores
        post.red_pens = [pen.model_dump(mode="json") for pen in itd_post.red_pens]
        post.red_pen_authors = [str(c.actor.id) for c in itd_post.red_pen.claims]
        post.correctors = [
            {
                "id": str(c.id),
                "start": c.start,
                "end": c.end,
                "actor": str(c.actor.id),
                "created_at": str(c.created_at)
            }
            for c in itd_post.correctors
        ]
        post.exists = True
        # comments are refetched only when the counter moved, like the scraper does
        if comments_changed:
            deleted = save_comments(db, post_id, fetch_comment_tree(itd_post), True)
            l.debug("post %s: comments refetched, %s deleted", post_id, deleted)
    except (NotFoundError, TargetUserBannedError):
        db.rollback()
        post = db.query(Post).where(Post.post_id == post_id).one()
        post.exists = False
    except Exception as error:
        db.rollback()
        l.warning("post %s refresh failed: %r", post_id, error)
        raise HTTPException(502, "ITD request failed") from error
    db.commit()
    return get_post_response(db, post_id)
