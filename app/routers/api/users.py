from typing import cast

from fastapi import APIRouter, Depends

from app.services.neon import get_db, Session
from app.schemas.user import User

router = APIRouter(prefix='/users')

@router.get('/')
def api_get_users(
    db: Session = Depends(get_db),
    offset: int = 0
):
    return db.query(User).order_by(User.followers).offset(offset).limit(100).all()


@router.get('/graph')
def api_get_users_graph(
    db: Session = Depends(get_db)
):
    users = db.query(User).all()#.where(User.following_users != []).all()
    user_ids = {str(user.user_id): user.id for user in users}

    edges = []
    for user in users:
        for target in user.following_users:
            if str(target) in user_ids:
                edges.append({'source': int(user.id), 'target': int(user_ids[str(target)])})

    return {'nodes': users, 'edges': edges}

@router.get('/search')
def api_get_user_search(query: str, db: Session = Depends(get_db)):
    return {'results': db.query(User).where(User.username.ilike(f'%{query}%')).limit(10).all()}