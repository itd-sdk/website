from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import desc

from app.services.db import get_db, Session
from app.schemas.app import App
from app.schemas.user import User

router = APIRouter(prefix='/ebdi')


class UserBody(BaseModel):
    created_at: datetime
    username: str
    display_name: str
    followers: list[UUID]
    following: list[UUID]
    followers_count: int
    following_count: int
    posts_count: int
    verified: bool
    avatar: str


class UserResponse(UserBody):
    id: int
    user_id: UUID
    found_at: datetime
    has_itdp: bool

    @field_validator('followers', 'following', mode='before')
    @classmethod
    def parse_uuid_list(cls, v):
        if isinstance(v, str):
            return eval(v)
        return v


class UserOrder(str, Enum):
    followers = 'followers'
    following = 'following'
    posts = 'posts'
    created_at = 'created_at'
    found_at = 'found_at'
    updated_at = 'updated_at'


@router.get('/users', response_model=list[UserResponse])
def api_get_ebdi_users(
    offset: int = 0,
    order: UserOrder = UserOrder.followers,
    descending: bool = True,
    db: Session = Depends(get_db)
):
    col = getattr(User, order.value)
    return [UserResponse.model_validate(user, from_attributes=True) for user in db.query(User).order_by(desc(col) if descending else col).offset(offset).limit(100).all()]


@router.post('/users')
def api_post_ebdi(
    app_token: str, id: UUID, body: UserBody, db: Session = Depends(get_db)
):
    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        return JSONResponse({'detail': 'invalid app token'}, 401)

    if db.query(User).where(User.user_id == id).first() is not None:
        return JSONResponse({'detail': 'user already exists'}, 409)

    user = User(
        user_id=id,
        created_at=body.created_at,
        username=body.username,
        display_name=body.display_name,
        followed_by_users=str(body.followers),
        following_users=str(body.following),
        followers=body.followers_count,
        following=body.following_count,
        posts=body.posts_count,
        verified=body.verified,
        avatar=body.avatar
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    app.added += 1
    return user


@router.put('/users/{id}', status_code=204)
def api_put_ebdi_users(
    app_token: str, id: UUID, body: UserBody, db: Session = Depends(get_db)
):
    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        return JSONResponse({'detail': 'invalid app token'}, 401)

    user = db.query(User).where(User.user_id == id).first()
    if user is None:
        return JSONResponse({'detail': 'user not found'}, 404)

    user.created_at = body.created_at
    user.username = body.username
    user.display_name = body.display_name
    user.followed_by_users = str(body.followers)
    user.following_users = str(body.following)
    user.followers = body.followers_count
    user.following = body.following_count
    user.posts = body.posts_count
    user.verified = body.verified
    user.avatar = body.avatar

    db.commit()
    app.refreshed += 1


@router.delete('/users/{id}', status_code=204)
def api_delete_ebdi_users(app_token: str, id: UUID, db: Session = Depends(get_db)):
    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        return JSONResponse({'detail': 'invalid app token'}, 401)

    user = db.query(User).where(User.user_id == id).first()
    if user is None:
        return JSONResponse({'detail': 'user not found'}, 404)

    user.exists = False
    db.commit()
    app.refreshed += 1


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
