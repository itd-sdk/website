from datetime import datetime

from app.schemas import User, UserSnapshot
from app.services.db import Session

State = tuple[int, int, int, bool]


def user_state(user: User) -> State:
    return (user.followers_count, user.following_count, user.posts_count, user.exists)


def record_changes(db: Session, user: User, before: State | None, at: datetime) -> None:
    """Add a snapshot if the counters differ from `before` (None for a new user)"""
    if before == user_state(user):
        return
    db.add(
        UserSnapshot(
            user_id=user.user_id,
            recorded_at=at,
            followers_count=user.followers_count,
            following_count=user.following_count,
            posts_count=user.posts_count,
            exists=user.exists
        )
    )
