from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from uvicorn import run

from app.logger import format_request, get_logger, setup_logging
from app.routers import router
from app.routers.api import router as api_router
from app.services.db import create_db
from app.services.github_service import get_analogs, get_projects
from app.services.turnstile import start_browser, stop_browser

BASE_DIR = Path(__file__).resolve().parent / "app"


@asynccontextmanager
async def lifespan(app: FastAPI):
    l.info("start server")
    await start_browser()
    yield
    l.info("stop server")
    await stop_browser()


app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
templates = Jinja2Templates(directory="app/templates/")

load_dotenv()
create_db()
setup_logging("DEBUG")
l = get_logger()

app.state.projects = get_projects()
app.state.analogs = get_analogs()
app.state.users_count_updated_at = datetime(1990, 1, 1)
app.state.graph_updated_at = datetime(1990, 1, 1)
app.state.is_loginning = False


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
