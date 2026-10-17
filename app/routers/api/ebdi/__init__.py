from fastapi import APIRouter

from app.routers.api.ebdi import clans, comments, posts, stats, users, websocket

router = APIRouter(prefix="/ebdi")
router.include_router(users.router)
router.include_router(clans.router)
router.include_router(websocket.router)
router.include_router(stats.router)
router.include_router(posts.router)
router.include_router(comments.router)
