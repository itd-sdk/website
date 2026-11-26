from functools import cache
from hashlib import md5
from pathlib import Path

from fastapi.templating import Jinja2Templates

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@cache
def static_version(path: str) -> str:
    # static files change only with a deploy, which restarts the server
    try:
        return md5((STATIC_DIR / path).read_bytes()).hexdigest()[:8]
    except OSError:
        return "0"


def static_url(path: str) -> str:
    """URL of a static file that changes with its content, so browsers and
    Cloudflare never serve an old copy of a changed script or style"""
    return f"/static/{path}?v={static_version(path)}"


def get_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory="app/templates/")
    templates.env.globals["static"] = static_url
    return templates
