from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.schemas import Epepuy
from app.services.db import get_db

router = APIRouter(prefix="/ebdi")
templates = Jinja2Templates(directory="app/templates/")


@router.get("/")
def get_ebdi(request: Request):
    # return templates.TemplateResponse(request, "ebdi/index.html")
    return RedirectResponse("/ebdi/users")


@router.get("/users")
def get_ebdi_users(request: Request):
    return templates.TemplateResponse(request, "ebdi/users.html")


@router.get("/clans")
def get_ebdi_clans(request: Request):
    return templates.TemplateResponse(request, "ebdi/clans.html")


@router.get("/graph")
def get_ebdi_graph(request: Request):
    return templates.TemplateResponse(request, "ebdi/graph.html")


@router.get("/epepuy")
def get_ebdi_epepuy(request: Request, db: Session = Depends(get_db)):
    images = db.query(Epepuy).order_by(func.random()).limit(500).all()
    return templates.TemplateResponse(
        request,
        "ebdi/epepuy/index.html",
        {
            "images": [
                f"https://cdn.xn--d1ah4a.com/images/{image.file_id}.jpg"
                for image in images
            ]
        }
    )


@router.get("/epepuy/raw")
def get_ebdi_epepuy_raw(request: Request, db: Session = Depends(get_db)):
    image = db.query(Epepuy).order_by(func.random()).first()
    if not image:
        return JSONResponse({"detail": "no images"}, 404)
    return templates.TemplateResponse(
        request,
        "ebdi/epepuy/raw.html",
        {"url": f"https://cdn.xn--d1ah4a.com/images/{image.file_id}.jpg"}
    )
