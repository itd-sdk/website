from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.routers import router
from app.services.github_service import get_analogs, get_projects

BASE_DIR = Path(__file__).resolve().parent / "app"

app = FastAPI(docs_url=None, redoc_url=None)

app.state.projects = get_projects()
app.state.analogs = get_analogs()

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(router)

@app.get('/favicon.ico')
def get_favicon():
    return FileResponse(BASE_DIR / 'static' / 'favicon.ico')