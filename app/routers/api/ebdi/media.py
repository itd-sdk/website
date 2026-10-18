"""Same-origin copies of ITD voice messages.

The ITD CDN sends no CORS headers, so the page cannot read the files to draw
waveforms or decode the ones Firefox fails to open (phone recordings).
"""

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
MAX_AUDIO_SIZE = 20 * 1024 * 1024


@router.get("/audio/{name}")
@get_limiter().limit("120/minute")
async def api_get_ebdi_audio(request: Request, name: str = Path(pattern=AUDIO_NAME)):
    # only files of the ITD CDN by name, the endpoint is not an open proxy
    try:
        async with (
            httpx.AsyncClient(timeout=15) as client,
            client.stream("GET", AUDIO_SOURCE + name) as res
        ):
            if res.status_code != 200:
                raise HTTPException(404 if res.status_code == 404 else 502)
            content = bytearray()
            async for chunk in res.aiter_bytes():
                content += chunk
                if len(content) > MAX_AUDIO_SIZE:
                    raise HTTPException(413, "file too large")
            media_type = res.headers.get("content-type", "audio/ogg")
    except httpx.HTTPError as error:
        l.warning("audio %s fetch failed: %r", name, error)
        raise HTTPException(502, "ITD request failed") from error
    # files never change under the same name
    return Response(
        bytes(content),
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=604800, immutable"}
    )
