from fastapi import APIRouter

from app.routers.api import ebdi, users

router = APIRouter(prefix="/api")
router.include_router(users.router)
router.include_router(ebdi.router)
