from time import sleep

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.login import login

router = APIRouter(prefix='/login')

@router.get('/')
def api_post_login(request: Request, username: str, password: str):
    while request.app.state.is_loginning:
        sleep(0.1)

    print('start')
    request.app.state.is_loginning = True
    sleep(5)
    token = login(username, password)
    request.app.state.is_loginning = False
    if token:
        return {'refresh_token': 'token'}
    return JSONResponse({'detail': 'failed to login (internal server error, invalid credentials, servers down, etc)'}, 400)
