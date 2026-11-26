from fastapi import APIRouter, Request

from app.services.templates import get_templates


router = APIRouter()
templates = get_templates()


@router.get('/')
def get_root(request: Request):
    return templates.TemplateResponse(request, 'index.html', {'projects': request.app.state.projects, 'analogs': request.app.state.analogs})