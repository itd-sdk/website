from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/graph")
templates = Jinja2Templates(directory="app/templates/")


@router.get("/")
def get_graph(request: Request):
    return RedirectResponse("/ebdi/graph")
