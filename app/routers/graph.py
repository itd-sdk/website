from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.services.templates import get_templates

router = APIRouter(prefix="/graph")
templates = get_templates()


@router.get("/")
def get_graph(request: Request):
    return RedirectResponse("/ebdi/graph")
