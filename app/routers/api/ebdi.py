from json import dumps
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.services.db import get_db, Session
from app.schemas.app import App
from app.schemas.user import User

router = APIRouter(prefix='/ebdi')


@router.get('')
def api_get_ebdi(app_token: str, offset: int = 0, db: Session = Depends(get_db)):
    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        return JSONResponse({'detail': 'invalid app token'}, 401)

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
        'avatar': user.avatar
    } for user in db.query(User).offset(offset).limit(100).all()]


@router.post('')
def api_post_ebdi(
    app_token: str, id: UUID, created_at: datetime, username: str, display_name: str,
    followers: list[UUID], following: list[UUID], followers_count: int, following_count: int,
    posts_count: int, verified: bool, avatar: str, db: Session = Depends(get_db)
):
    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        return JSONResponse({'detail': 'invalid app token'}, 401)

    user = User(
        user_id=id,
        created_at=created_at,
        username=username,
        display_name=display_name,
        followed_by_users=str(followers),
        following_user=str(following),
        followers=followers_count,
        following=following_count,
        posts=posts_count,
        verified=verified,
        avatar=avatar
    )
    db.add(user)
    db.refresh(user)
    return user


@router.get('/task')
def api_get_task(app_token: str, db: Session = Depends(get_db)):
    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        return JSONResponse({'detail': 'invalid app token'}, 401)

    apps = db.query(App).all()

    to_update = db.query(User).where(User.updated_at < datetime.now() - timedelta(days=3)).all()
    for batch in range(len(to_update) // 100):
        if batch * 100 not in [_app.task_assigned_start for _app in apps]:
            app.task = 'update'
            app.task_target = 'user'
            app.task_assigned_start = batch * 100
            app.task_assigned_end = batch * 100 + 100
            db.commit()
            return {'task': 'update', 'start': batch * 100, 'end': batch * 100 + 100, 'users': [user.user_id for user in to_update[batch * 100:batch * 100 + 100]]}
