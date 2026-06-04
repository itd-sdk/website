from fastapi import APIRouter

from app.routers.api import ebdi, turnstile, users

router = APIRouter(prefix="/api")
router.include_router(users.router)
router.include_router(turnstile.router)
router.include_router(ebdi.router)
