from pathlib import Path
from os import getenv
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from app.routers import router
from app.routers.api import router as api_router
# from app.services.github_service import get_analogs, get_projects
from app.services.db import create_db

BASE_DIR = Path(__file__).resolve().parent / "app"

app = FastAPI(docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory="app/templates/")
create_db()

app.state.projects = []#get_projects()
app.state.analogs = []#get_analogs()
app.state.users_count_updated_at = datetime(1990, 1, 1)
app.state.graph_updated_at = datetime(1990, 1, 1)

@app.exception_handler(404)
def handle_404(request: Request, _):
    if not request.url.path.startswith('api'):
        return templates.TemplateResponse(request, '404.html', status_code=404)


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(router)
app.include_router(api_router)


@app.get('/favicon.ico')
def get_favicon():
    return FileResponse(BASE_DIR / 'static' / 'favicon.ico')
