from fastapi import APIRouter

from app.routers.api import users, login

router = APIRouter(prefix='/api')
router.include_router(users.router)
router.include_router(login.router)
