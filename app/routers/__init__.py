from fastapi import APIRouter

from app.routers import main, wiki

router = APIRouter()
router.include_router(main.router)
router.include_router(wiki.router)