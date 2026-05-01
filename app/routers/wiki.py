from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
from jinja2.exceptions import TemplateNotFound


router = APIRouter(prefix='/wiki')
templates = Jinja2Templates(directory="app/templates/")


@router.get('/{name}')
def get_root(request: Request, name: str):
    try:
        return templates.TemplateResponse(request, f'wiki/{name}.html')
    except TemplateNotFound:
        raise HTTPException(404)