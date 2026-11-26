from fastapi import APIRouter, HTTPException, Request
from jinja2.exceptions import TemplateNotFound

from app.services.templates import get_templates

router = APIRouter(prefix="/projects")
templates = get_templates()


@router.get("")
def get_root(request: Request):
    return templates.TemplateResponse(request, "projects/index.html")


@router.get("/{name}")
def get_projects(request: Request, name: str):
    try:
        return templates.TemplateResponse(request, f"projects/{name}.html")
    except TemplateNotFound:
        raise HTTPException(404)
