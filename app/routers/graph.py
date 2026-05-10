from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates


router = APIRouter(prefix='/graph')
templates = Jinja2Templates(directory="app/templates/")


@router.get('/')
def get_root(request: Request):
    return templates.TemplateResponse(request, 'graph.html')