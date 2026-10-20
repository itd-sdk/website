from os import getenv
from pathlib import Path as FilePath
from subprocess import run
from time import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import FileResponse
from requests import RequestException, Session

from app.logger import get_logger
from app.services.limiter import get_limiter

router = APIRouter(prefix="/media")
l = get_logger("ebdi.media")

AUDIO_SOURCE = "https://cdn.xn--d1ah4a.com/audio/"
AUDIO_NAME = (
    r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    r"\.(ogg|oga|opus|mp3|m4a|aac|wav|flac)$"
)
MEDIA_TYPES = {
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
    ".flac": "audio/flac"
}
OGG_SUFFIXES = (".ogg", ".oga", ".opus")
MAX_AUDIO_SIZE = 20 * 1024 * 1024
# files nobody played for this long are removed, played ones get a new term
CACHE_TTL = 7 * 24 * 3600
CLEANUP_INTERVAL = 3600

session = Session()
last_cleanup = 0.0


def cache_dir() -> FilePath:
    # read on use, .env is loaded after the routers are imported
    path = FilePath(getenv("AUDIO_CACHE_DIR", "cache/audio"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def remove_stale(directory: FilePath) -> None:
    deadline = time() - CACHE_TTL
    removed = 0
    for file in directory.iterdir():
        try:
            if file.stat().st_mtime < deadline:
                file.unlink()
                removed += 1
        except FileNotFoundError:
            pass
    if removed:
        l.info("removed %s stale voice messages", removed)


def download(name: str) -> bytes:
    res = session.get(AUDIO_SOURCE + name, timeout=15)
    if res.status_code != 200:
        raise HTTPException(404 if res.status_code == 404 else 502)
    if len(res.content) > MAX_AUDIO_SIZE:
        raise HTTPException(413, "file too large")
    return res.content


def remux_ogg(content: bytes) -> bytes:
    # stream copy: the container is written anew, the audio is not re-encoded
    process = run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-c",
            "copy",
            "-f",
            "ogg",
            "pipe:1"
        ],
        input=content,
        capture_output=True,
        timeout=10
    )
    if process.returncode != 0 or not process.stdout:
        raise RuntimeError(process.stderr.decode(errors="replace").strip())
    return process.stdout


@router.get("/audio/{name}")
@get_limiter().limit("60/minute")
def api_get_ebdi_audio(request: Request, name: str = Path(pattern=AUDIO_NAME)):
    # a plain def runs in the threadpool, so blocking downloads and ffmpeg are fine
    global last_cleanup
    directory = cache_dir()
    if time() - last_cleanup > CLEANUP_INTERVAL:
        last_cleanup = time()
        remove_stale(directory)

    file = directory / name
    if file.exists():
        file.touch()
    else:
        # only files of the итд CDN by name, the endpoint is not an open proxy
        try:
            content = download(name)
        except RequestException as error:
            l.warning("audio %s fetch failed: %r", name, error)
            raise HTTPException(502, "ITD request failed") from error
        if name.endswith(OGG_SUFFIXES):
            try:
                content = remux_ogg(content)
            except Exception as error:
                # the original still plays in most browsers
                l.warning("audio %s remux failed: %r", name, error)
        # a reader never sees a half written file
        partial = file.with_name(f".{name}.{uuid4().hex}.part")
        partial.write_bytes(content)
        partial.replace(file)
    # files never change under the same name
    return FileResponse(
        file,
        media_type=MEDIA_TYPES[file.suffix],
        headers={"Cache-Control": "public, max-age=604800, immutable"}
    )
