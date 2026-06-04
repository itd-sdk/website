# original by @itdStatus

from asyncio import sleep

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.logger import get_logger
from app.schemas.app import App
from app.services.db import Session, get_db
from app.services.turnstile import get_turnstile

router = APIRouter(prefix="/turnstile")
l = get_logger("api.turnstile")


@router.get("/")
async def api_get_token(
    request: Request, app_token: str, db: Session = Depends(get_db)
):
    app = db.query(App).where(App.token == app_token).first()
    if app is None:
        return JSONResponse({"detail": "invalid app token"}, 401)

    l.info("receive login")
    while request.app.state.is_loginning:
        await sleep(0.1)

    request.app.state.is_loginning = True
    l.info("start login")
    res = await get_turnstile()
    request.app.state.is_loginning = False
    return res
