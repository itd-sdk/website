from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request

from app.services.neon import get_db, Session
from app.schemas.user import User

router = APIRouter(prefix='/users')

@router.get('/')
def api_get_users(
    db: Session = Depends(get_db),
    offset: int = 0
):
    return db.query(User).order_by(User.followers).offset(offset).limit(100).all()


@router.get('/count')
def api_get_user_count(request: Request, db: Session = Depends(get_db)):
    if datetime.now() - request.app.state.users_count_updated_at > timedelta(hours=1):
        request.app.state.users_count = db.query(User).count()
        request.app.state.users_count_updated_at = datetime.now()
    return {'count': request.app.state.users_count}