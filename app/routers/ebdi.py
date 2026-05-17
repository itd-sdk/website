from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates


router = APIRouter(prefix='/ebdi')
templates = Jinja2Templates(directory="app/templates/")


@router.get('/')
def get_ebdi(request: Request):
    return templates.TemplateResponse(request, 'ebdi.html')