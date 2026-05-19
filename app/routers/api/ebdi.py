from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import desc

from app.services.db import get_db, Session
from app.schemas.app import App
from app.schemas.user import User

router = APIRouter(prefix='/ebdi')


class UserOrder(str, Enum):
    followers = 'followers'
    following = 'following'
    posts = 'posts'
    created_at = 'created_at'
    found_at = 'found_at'
    updated_at = 'updated_at'


@router.get('/users')
def api_get_ebdi_users(
    offset: int = 0,
    order: UserOrder = UserOrder.followers,
    descending: bool = True,
    db: Session = Depends(get_db)
):
    col = getattr(User, order.value)
    return [{
        'id': user.id,
        'user_id': user.user_id,
        'found_at': user.found_at,
        'created_at': user.created_at,
        'username': user.username,
        'display_name': user.display_name,
        'followers': eval(user.followed_by_users),
        'following': eval(user.following_users),
        'followers_count': user.followers,
        'following_count': user.following,
        'posts_count': user.posts,
        'verified': user.verified,
        'avatar': user.avatar,
        'has_itdp': user.has_itdp
    } for user in db.query(User).order_by(desc(col) if descending else col).offset(offset).limit(100).all()]


@router.post('/users')
def api_post_ebdi(
    app_token: str, id: UUID, created_at: datetime, username: str, display_name: str,
    followers: list[UUID], following: list[UUID], followers_count: int, following_count: int,
    posts_count: int, verified: bool, avatar: str, db: Session = Depends(get_db)
):
    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        return JSONResponse({'detail': 'invalid app token'}, 401)

    if db.query(User).where(User.user_id == id).first() is not None:
        return JSONResponse({'detail': 'user already exists'}, 409)

    user = User(
        user_id=id,
        created_at=created_at,
        username=username,
        display_name=display_name,
        followed_by_users=str(followers),
        following_users=str(following),
        followers=followers_count,
        following=following_count,
        posts=posts_count,
        verified=verified,
        avatar=avatar
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put('/users/{id}')
def api_put_ebdi_users(
    app_token: str, id: UUID, created_at: datetime, username: str, display_name: str,
    followers: list[UUID], following: list[UUID], followers_count: int, following_count: int,
    posts_count: int, verified: bool, avatar: str, db: Session = Depends(get_db)
):
    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        return JSONResponse({'detail': 'invalid app token'}, 401)

    user = db.query(User).where(User.user_id == id).first()
    if user is None:
        return JSONResponse({'detail': 'user not found'}, 404)

    user.created_at = created_at
    user.username = username
    user.display_name = display_name
    user.followed_by_users = str(followers)
    user.following_users = str(following)
    user.followers = followers_count
    user.following = following_count
    user.posts = posts_count
    user.verified = verified
    user.avatar = avatar

    db.commit()
    db.refresh(user)
    return user


@router.delete('/users/{id}')
def api_delete_ebdi_users(app_token: str, id: UUID, db: Session = Depends(get_db)):
    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        return JSONResponse({'detail': 'invalid app token'}, 401)

    user = db.query(User).where(User.user_id == id).first()
    if user is None:
        return JSONResponse({'detail': 'user not found'}, 404)

    user.exists = False
    db.commit()


@router.get('/task')
def api_get_task(app_token: str, db: Session = Depends(get_db)):
    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        return JSONResponse({'detail': 'invalid app token'}, 401)

    # ai begin ---
    assigned_starts = {a.task_assigned_start for a in db.query(App).all()}
    stale_cutoff = datetime.now() - timedelta(days=3)
    total = db.query(User).where(User.updated_at < stale_cutoff).count()

    for batch in range(total // 100):
        start = batch * 100
        if start not in assigned_starts:
            app.task = 'update'
            app.task_target = 'user'
            app.task_assigned_start = start
            app.task_assigned_end = start + 100
            db.commit()
            users = db.query(User).where(User.updated_at < stale_cutoff).order_by(User.followers.desc()).offset(start).limit(100).all()

            return {'task': 'update', 'start': start, 'end': start + 100, 'users': [u.user_id for u in users]}

    # --- ai end
    return {'task': 'no'}
