from pathlib import Path
from os import getenv

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from app.routers import router
from app.routers.api import router as api_router
from app.services.github_service import get_analogs, get_projects
from app.services.neon import create_db

BASE_DIR = Path(__file__).resolve().parent / "app"
load_dotenv()

app = FastAPI(docs_url=None, redoc_url=None)
create_db(getenv('DATABASE_URL', ''))

app.state.projects = get_projects()
app.state.analogs = get_analogs()

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(router)
app.include_router(api_router)

@app.get('/favicon.ico')
def get_favicon():
    return FileResponse(BASE_DIR / 'static' / 'favicon.ico')