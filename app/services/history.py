from datetime import datetime

from sqlalchemy import exists

from app.schemas import User, UserProfileSnapshot, UserSnapshot
from app.services.db import Session

Counters = tuple[int, int, int, bool]
Profile = dict[str, str | None]
State = tuple[Counters, Profile, datetime]

PROFILE_FIELDS = ("username", "display_name", "avatar", "bio", "banner")


def counters_state(user: User) -> Counters:
    return (user.followers_count, user.following_count, user.posts_count, user.exists)


def profile_state(user: User) -> Profile:
    return {field: getattr(user, field) for field in PROFILE_FIELDS}


def user_state(user: User) -> State:
    return counters_state(user), profile_state(user), user.updated_at


def counters_snapshot(user: User, counters: Counters, at: datetime) -> UserSnapshot:
    return UserSnapshot(
        user_id=user.user_id,
        recorded_at=at,
        followers_count=counters[0],
        following_count=counters[1],
        posts_count=counters[2],
        exists=counters[3]
    )


def has_snapshots(db: Session, model, user: User) -> bool:
    return bool(db.query(exists().where(model.user_id == user.user_id)).scalar())


def record_changes(db: Session, user: User, before: State | None, at: datetime) -> None:
    """Add snapshots of what differs from `before` (None for a new user).

    The counters and the profile are kept apart, they change independently.
    A user without snapshots yet (stored before the history existed) also
    gets the state before the change, at its previous update, so the first
    change keeps its old value.
    """
    counters, profile, _ = user_state(user)
    if before is None or before[0] != counters:
        if before is not None and not has_snapshots(db, UserSnapshot, user):
            db.add(counters_snapshot(user, before[0], before[2]))
        db.add(counters_snapshot(user, counters, at))
    if before is None or before[1] != profile:
        if before is not None and not has_snapshots(db, UserProfileSnapshot, user):
            db.add(
                UserProfileSnapshot(
                    user_id=user.user_id, recorded_at=before[2], data=before[1]
                )
            )
        db.add(UserProfileSnapshot(user_id=user.user_id, recorded_at=at, data=profile))
