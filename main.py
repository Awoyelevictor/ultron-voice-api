import asyncio
import logging
import os
import time

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("ultron.voice")

app = FastAPI(title="ULTRON Voice API")

TTS_API = os.getenv(
    "TTS_API_URL",
    "https://michsethowusuwfp3--africa-tts-api-api.us-east.modal.run",
).rstrip("/")
API_SECRET = os.getenv("ULTRON_VOICE_SECRET", "")


class SpeechRequest(BaseModel):
    text: str
    lang: str = "eng"


def get_voice_path() -> str:
    return os.getenv(
        "VOICE_REFERENCE_PATH",
        "/etc/secrets/ultron_reference.b64",
    )


@app.get("/")
async def home():
    return FileResponse("web/index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness():
    voice_path = get_voice_path()
    return {
        "status": "ready" if API_SECRET and os.path.isfile(voice_path) else "degraded",
        "api_secret_configured": bool(API_SECRET),
        "voice_reference_configured": os.path.isfile(voice_path),
    }


@app.post("/speak")
async def speak(data: SpeechRequest, x_api_key: str = Header(default="")):
    if not API_SECRET or x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    text = data.text.strip()
    if not text or len(text) > 2000:
        raise HTTPException(status_code=400, detail="Text must be 1–2000 characters")

    voice_path = get_voice_path()
    if not os.path.isfile(voice_path):
        logger.error("Voice reference file is missing at configured path")
        raise HTTPException(status_code=503, detail="Voice reference is not configured")

    try:
        with open(voice_path, "r", encoding="utf-8") as audio_file:
            voice_b64 = audio_file.read().strip()
    except OSError:
        logger.exception("Could not read configured voice reference file")
        raise HTTPException(status_code=503, detail="Voice reference could not be read")

    if not voice_b64:
        logger.error("Voice reference file is empty")
        raise HTTPException(status_code=503, detail="Voice reference is empty")

    payload = {
        "text": text,
        "lang": data.lang,
        "format": "wav",
        "voice_wav_base64": voice_b64,
    }

    timeout = httpx.Timeout(connect=15.0, read=85.0, write=30.0, pool=15.0)
    started = time.monotonic()
    last_status = None

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for attempt in range(2):
            try:
                result = await client.post(f"{TTS_API}/v1/tts", json=payload)

                if result.status_code in (500, 502, 503, 504) and attempt == 0:
                    logger.warning(
                        "TTS provider returned HTTP %s; retrying once",
                        result.status_code,
                    )
                    await asyncio.sleep(1.0)
                    continue

                if result.status_code == 429:
                    logger.warning("TTS provider rate-limited the request")
                    raise HTTPException(
                        status_code=503,
                        detail="TTS provider is rate-limiting requests; try again shortly",
                    )

                result.raise_for_status()

                if not result.content.startswith(b"RIFF"):
                    logger.error(
                        "TTS provider returned non-WAV data (content-type=%s, bytes=%s)",
                        result.headers.get("content-type", "unknown"),
                        len(result.content),
                    )
                    raise HTTPException(
                        status_code=502,
                        detail="TTS provider returned invalid audio",
                    )

                logger.info(
                    "Speech generated successfully in %.2fs (%s bytes)",
                    time.monotonic() - started,
                    len(result.content),
                )
                return Response(content=result.content, media_type="audio/wav")

            except httpx.HTTPStatusError as exc:
                last_status = exc.response.status_code
                body = (exc.response.text or "")[:500].replace("\\n", " ")
                logger.error(
                    "TTS provider HTTP %s after attempt %s: %s",
                    last_status,
                    attempt + 1,
                    body,
                )
                if attempt == 0 and last_status in (500, 502, 503, 504):
                    await asyncio.sleep(1.0)
                    continue
                raise HTTPException(
                    status_code=502,
                    detail=f"TTS provider returned HTTP {last_status}",
                ) from exc

            except httpx.TimeoutException as exc:
                logger.error("TTS provider timed out after %.2fs", time.monotonic() - started)
                raise HTTPException(
                    status_code=504,
                    detail="TTS provider took too long to respond; try again",
                ) from exc

            except httpx.RequestError as exc:
                logger.error("Could not reach TTS provider: %s", type(exc).__name__)
                raise HTTPException(
                    status_code=502,
                    detail="Could not reach TTS provider",
                ) from exc

    logger.error("TTS request failed after retries (last_status=%s)", last_status)
    raise HTTPException(status_code=502, detail="TTS provider failed after retry")


# SONIVOX web interface assets; the legacy /speak API remains unchanged.
app.mount("/assets", StaticFiles(directory="web/assets"), name="assets")
