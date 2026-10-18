"""Same-origin copies of ITD voice messages.

The ITD CDN sends no CORS headers, so the page cannot read the files to draw
waveforms. Phone recordings also start at a negative time (the first ogg page
holds fewer samples than its granule position says), which Firefox rejects;
ffmpeg rebuilds the container without touching the audio.
"""

import asyncio
import shutil
from collections import OrderedDict

import httpx
from fastapi import APIRouter, HTTPException, Path, Request, Response

from app.logger import get_logger
from app.services.limiter import get_limiter

router = APIRouter(prefix="/media")
l = get_logger("ebdi.media")

AUDIO_SOURCE = "https://cdn.xn--d1ah4a.com/audio/"
AUDIO_NAME = (
    r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    r"\.(ogg|oga|opus|mp3|m4a|aac|wav|flac)$"
)
OGG_SUFFIXES = (".ogg", ".oga", ".opus")
MAX_AUDIO_SIZE = 20 * 1024 * 1024
CACHE_SIZE = 64 * 1024 * 1024
FFMPEG = shutil.which("ffmpeg")

client: httpx.AsyncClient | None = None
# recently served files, the same voice message is usually played by many viewers
cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
cache_bytes = 0

if FFMPEG is None:
    l.warning("ffmpeg not found, ogg voice messages are served as is")


async def download(name: str) -> tuple[bytes, str]:
    global client
    client = client or httpx.AsyncClient(timeout=15)
    async with client.stream("GET", AUDIO_SOURCE + name) as res:
        if res.status_code != 200:
            raise HTTPException(404 if res.status_code == 404 else 502)
        content = bytearray()
        async for chunk in res.aiter_bytes():
            content += chunk
            if len(content) > MAX_AUDIO_SIZE:
                raise HTTPException(413, "file too large")
        return bytes(content), res.headers.get("content-type", "audio/ogg")


async def remux_ogg(content: bytes) -> bytes:
    # stream copy: the container is written anew, the audio is not re-encoded
    process = await asyncio.create_subprocess_exec(
        FFMPEG, "-loglevel", "error", "-i", "pipe:0", "-c", "copy", "-f", "ogg",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    try:
        output, error = await asyncio.wait_for(process.communicate(content), 10)
    except TimeoutError:
        process.kill()
        raise
    if process.returncode != 0 or not output:
        raise RuntimeError(error.decode(errors="replace").strip())
    return output


def remember(name: str, value: tuple[bytes, str]) -> None:
    global cache_bytes
    cache[name] = value
    cache_bytes += len(value[0])
    while cache_bytes > CACHE_SIZE:
        _, (content, _) = cache.popitem(last=False)
        cache_bytes -= len(content)


@router.get("/audio/{name}")
@get_limiter().limit("120/minute")
async def api_get_ebdi_audio(request: Request, name: str = Path(pattern=AUDIO_NAME)):
    # only files of the ITD CDN by name, the endpoint is not an open proxy
    if name in cache:
        cache.move_to_end(name)
        content, media_type = cache[name]
    else:
        try:
            content, media_type = await download(name)
        except httpx.HTTPError as error:
            l.warning("audio %s fetch failed: %r", name, error)
            raise HTTPException(502, "ITD request failed") from error
        if FFMPEG and name.endswith(OGG_SUFFIXES):
            try:
                content = await remux_ogg(content)
            except Exception as error:
                # the original still plays in most browsers
                l.warning("audio %s remux failed: %r", name, error)
        remember(name, (content, media_type))
    # files never change under the same name
    return Response(
        content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=604800, immutable"}
    )
