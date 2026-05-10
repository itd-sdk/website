from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

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
    if datetime.now() - request.app.state.graph_updated_at > timedelta(hours=3):
        # ai begin ---
        nodes = db.execute(text("""
            SELECT id, username, display_name, followers, following, verified, avatar
            FROM users
        """)).mappings().all()

        edges_raw = db.execute(text("""
            SELECT u1.id AS source, u2.id AS target
            FROM users u1
            CROSS JOIN LATERAL unnest(u1.following_users) AS fuid
            JOIN users u2 ON u2.user_id = fuid
            WHERE u1.following_users != '{}'

            UNION

            SELECT u2.id AS source, u1.id AS target
            FROM users u1
            CROSS JOIN LATERAL unnest(u1.followed_by_users) AS fuid
            JOIN users u2 ON u2.user_id = fuid
            WHERE u1.followed_by_users != '{}'
        """)).fetchall()

        all_node_ids = {n['id'] for n in nodes}
        pair_set = {(s, t) for s, t in edges_raw if s in all_node_ids and t in all_node_ids}
        node_ids_with_edges = {id for pair in pair_set for id in pair}

        seen = set()
        edges = []
        for s, t in pair_set:
            key = frozenset([s, t])
            if key not in seen:
                seen.add(key)
                edges.append({'source': s, 'target': t, 'mutual': (t, s) in pair_set})
        # --- ai end

        request.app.state.graph = {
            'nodes': [dict(n) for n in nodes if n['id'] in node_ids_with_edges],
            'edges': edges
        }
        request.app.state.graph_updated_at = datetime.now()

    return request.app.state.graph


@router.get('/search')
def api_get_user_search(query: str, db: Session = Depends(get_db)):
    return {'results': db.query(User).where(User.username.ilike(f'%{query}%')).limit(10).all()}
