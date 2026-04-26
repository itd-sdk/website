from fastapi import APIRouter

from app.routers import main, graph

router = APIRouter()
router.include_router(main.router)
router.include_router(graph.router)