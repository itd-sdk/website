from fastapi import APIRouter

from app.routers.api import ebdi

router = APIRouter(prefix="/api")
router.include_router(ebdi.router)
