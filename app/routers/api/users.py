from json import dumps
from datetime import datetime, timedelta
from uuid import UUID # i swear we need this

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import or_

from app.services.db import get_db, Session
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

@router.get('/graph')
def api_get_users_graph(request: Request, db: Session = Depends(get_db)):
    if datetime.now() - request.app.state.graph_updated_at > timedelta(hours=6):
        users = db.query(User).where(or_(User.followers > 0, User.following > 0)).all()
        user_ids = {str(user.user_id): user.id for user in users}

        edges: set[tuple[int, int]] = set()
        for user in users:
            for target in eval(user.following_users) + eval(user.followed_by_users):
                target_id = user_ids.get(str(target))
                if target_id is not None and (target_id, user.id) not in edges:
                    edges.add((user.id, target_id))

        nodes = [
            {
                'id': u.id,
                'username': u.username,
                'display_name': u.display_name,
                'followers': u.followers,
                'following': u.following,
                'verified': u.verified,
                'avatar': u.avatar
            } for u in users
        ]

        request.app.state.graph = dumps(
            {'nodes': nodes, 'edges': [{'source': s, 'target': t} for s, t in edges]}
        )
        request.app.state.graph_updated_at = datetime.now()

    return Response(content=request.app.state.graph, media_type='application/json')


@router.get('/search')
def api_get_user_search(query: str, db: Session = Depends(get_db)):
    return {'results': db.query(User).where(User.username.ilike(f'%{query}%')).limit(10).all()}
