from fastapi import APIRouter

from app.routers import main, wiki, graph, ebdi

router = APIRouter()
router.include_router(main.router)
router.include_router(wiki.router)
router.include_router(graph.router)
router.include_router(ebdi.router)
