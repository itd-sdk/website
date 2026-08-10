from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import desc, func

from app.schemas import User
from app.services.db import Session, get_db
from app.services.limiter import get_limiter

router = APIRouter(prefix="/clans")


class ClanResponse(BaseModel):
    rank: int
    clan: str
    users_count: int


@router.get("/", response_model=list[ClanResponse])
@get_limiter().limit("15/minute")
def api_get_ebdi_clans(request: Request, db: Session = Depends(get_db)):
    rows = (
        db.query(User.avatar, func.count(User.id).label("users_count"))
        .where(User.exists.is_(True))
        .group_by(User.avatar)
        .order_by(desc("users_count"), User.avatar)
        .all()
    )
    return [
        ClanResponse(rank=i + 1, clan=clan, users_count=count)
        for i, (clan, count) in enumerate(rows)
    ]
