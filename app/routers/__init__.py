from fastapi import APIRouter

from app.routers import main

router = APIRouter()
router.include_router(main.router)