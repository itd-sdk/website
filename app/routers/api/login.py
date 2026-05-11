from time import sleep

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.login import login
from app.logger import get_logger

router = APIRouter(prefix='/login')
l = get_logger('api.login')

@router.get('/')
def api_get_login(request: Request, email: str, password: str):
    l.info('receive login')
    while request.app.state.is_loginning:
        sleep(0.1)

    request.app.state.is_loginning = True
    l.info('start login')
    token = login(email, password)
    request.app.state.is_loginning = False
    if token:
        l.info('finish login')
        return {'refresh_token': token}
    return JSONResponse({'detail': 'failed to login (internal server error, invalid credentials, servers down, etc)'}, 400)
