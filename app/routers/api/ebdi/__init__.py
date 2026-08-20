from fastapi import APIRouter

from app.routers.api.ebdi import clans, stats, users, websocket

router = APIRouter(prefix="/ebdi")
router.include_router(users.router)
router.include_router(clans.router)
router.include_router(websocket.router)
router.include_router(stats.router)
