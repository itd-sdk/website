from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates


router = APIRouter()
templates = Jinja2Templates(directory="app/templates/")


@router.get('/')
def get_root(request: Request):
    return templates.TemplateResponse(request, 'index.html', {'projects': request.app.state.projects, 'analogs': request.app.state.analogs})