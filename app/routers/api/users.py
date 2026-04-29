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


@router.get('/graph')
def api_get_users_graph(request: Request, db: Session = Depends(get_db)):
    if datetime.now() - request.app.state.graph_updated_at > timedelta(hours=6):
        users = db.query(User).all()
        user_ids = {str(user.user_id): user.id for user in users}

        pairs: set[tuple[int, int]] = set()
        for user in users:
            for target in user.following_users + user.followed_by_users:
                target_id = user_ids.get(str(target))
                if target_id is not None:
                    pairs.add((user.id, target_id))

        seen_pairs: set[frozenset[int]] = set()
        seen_users: set[int] = set()
        edges = []
        for source, target in pairs:
            pair = frozenset([source, target])

            if pair not in seen_pairs:
                seen_pairs.add(pair)
                seen_users.add(source)
                seen_users.add(target)
                edges.append({'source': source, 'target': target, 'mutual': (target, source) in pairs})

        request.app.state.graph = {'nodes': [user for user in users if user.id in seen_users], 'edges': edges}
        request.app.state.graph_updated_at = datetime.now()

    return request.app.state.graph

@router.get('/search')
def api_get_user_search(query: str, db: Session = Depends(get_db)):
    return {'results': db.query(User).where(User.username.ilike(f'%{query}%')).limit(10).all()}