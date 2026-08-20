from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from uvicorn import run

from app.logger import format_request, get_logger, setup_logging
from app.routers import router
from app.services.db import create_db
from app.services.github_service import get_analogs, get_projects
from app.services.limiter import set_limiter

BASE_DIR = Path(__file__).resolve().parent / "app"


@asynccontextmanager
async def lifespan(app: FastAPI):
    l.info("start server")
    yield
    l.info("stop server")


app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
templates = Jinja2Templates(directory="app/templates/")
limiter = Limiter(get_remote_address, default_limits=["2/second"])

set_limiter(limiter)
load_dotenv()
create_db()
setup_logging("DEBUG")
l = get_logger()

app.state.projects = get_projects()
app.state.analogs = get_analogs()
app.state.graph_updated_at = datetime.min
app.state.stats = {}
app.state.stats_updated_at = datetime.min
app.state.users_count_updated_at = datetime.min
app.state.is_loginning = False
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # ty: ignore
app.add_middleware(SlowAPIMiddleware)

from app.routers.api import router as api_router  # noqa


@app.exception_handler(404)
def handle_404(request: Request, _):
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": "not found"}, status_code=404)
    return templates.TemplateResponse(request, "404.html", status_code=404)


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(router)
app.include_router(api_router)


@app.middleware("http")
async def middleware(request: Request, call_next: Callable) -> Response:
    response: Response = await call_next(request)
    # custom access log
    l.info(format_request(request, response), extra={"highlighter": None})
    return response


@app.get("/favicon.ico")
def get_favicon():
    return FileResponse(BASE_DIR / "static" / "favicon.ico")


run(app, host="127.0.0.1", port=8997, log_level="warning", ws_ping_timeout=60)
