"""Saving scraped posts and comments, shared by the websocket and refresh endpoints"""

from collections.abc import Iterator
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app.routers.api.ebdi.protocol import CommentBody
from app.schemas import Comment, Post, User
from app.services.db import Session


def flatten_comments(
    comments: list[CommentBody], post_id: UUID, parent_id: UUID | None = None
) -> Iterator[dict]:
    # parents always go before their replies so the parent_id fk is satisfied
    for comment in comments:
        replies_count = comment.replies_count
        if replies_count is None:
            replies_count = len(comment.replies)
        yield {
            **comment.model_dump(exclude={"replies"}),
            "replies_count": replies_count,
            "post_id": post_id,
            "parent_id": parent_id
        }
        yield from flatten_comments(comment.replies, post_id, comment.comment_id)


def upsert(db: Session, model: type[Post] | type[Comment], key: str, rows: list[dict]):
    # chunks keep a single statement below the postgres bind parameters limit
    for i in range(0, len(rows), 1000):
        stmt = insert(model).values(rows[i : i + 1000])
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=[key],
                set_={c: stmt.excluded[c] for c in rows[0] if c != key}
            )
        )


def save_comments(
    db: Session, post_id: UUID, comments: list[CommentBody], complete: bool
) -> int:
    """Upsert the comment tree, returns how many stored comments were marked deleted.

    complete means the tree holds every comment of the post, so stored comments
    missing in it were deleted.
    """
    # same comment can come twice (pagination shifts), one insert
    # with duplicate keys fails, so keep the first occurrence
    rows: dict[UUID, dict] = {}
    for row in flatten_comments(comments, post_id):
        rows.setdefault(row["comment_id"], {**row, "exists": True, "deleted_at": None})
    upsert(db, Comment, "comment_id", list(rows.values()))
    if not complete:
        return 0
    return (
        db.query(Comment)
        .where(Comment.post_id == post_id)
        .where(Comment.exists.is_(True))
        .where(Comment.comment_id.not_in(rows.keys()))
        .update(
            {Comment.exists: False, Comment.deleted_at: func.now()},
            synchronize_session=False
        )
    )


def delete_user_comments(db: Session, user_id: UUID) -> int:
    # ITD removes all comments of a banned user but keeps the comment counters,
    # so the comments would never be refetched and have to be marked here
    return (
        db.query(Comment)
        .where(Comment.author_id == user_id)
        .where(Comment.exists.is_(True))
        .update(
            {Comment.exists: False, Comment.deleted_at: func.now()},
            synchronize_session=False
        )
    )


def set_user_exists(db: Session, user: User, exists: bool) -> None:
    """Keeps deleted_at with exists, a missing user loses their comments"""
    if exists:
        user.deleted_at = None
    else:
        if user.exists:
            user.deleted_at = func.now()
        delete_user_comments(db, user.user_id)
    user.exists = exists
