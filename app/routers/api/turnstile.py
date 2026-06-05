from asyncio import sleep
from os import getenv

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.logger import get_logger
from app.services.turnstile import get_turnstile

router = APIRouter(prefix="/turnstile")
l = get_logger("api.turnstile")


@router.get("/")
async def api_get_token(request: Request, key: str):
    if key != getenv("TURNSTILE_APIKEY"):
        return JSONResponse({"detail": "invalid key"}, 401)

    l.info("receive login")
    while request.app.state.is_loginning:
        await sleep(0.1)

    request.app.state.is_loginning = True
    l.info("start login")
    res = await get_turnstile()
    request.app.state.is_loginning = False
    return res
