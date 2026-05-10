from fastapi import APIRouter

from app.routers import main, wiki, graph

router = APIRouter()
router.include_router(main.router)
router.include_router(wiki.router)
router.include_router(graph.router)
