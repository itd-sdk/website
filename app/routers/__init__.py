from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.routers import ebdi, graph, main, projects

router = APIRouter()
router.include_router(main.router)
router.include_router(projects.router)
router.include_router(graph.router)
router.include_router(ebdi.router)


@router.get("/wiki/{name}")
def get_wiki(name: str):
    return RedirectResponse(f"/projects/{name}")
