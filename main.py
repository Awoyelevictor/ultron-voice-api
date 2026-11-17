import asyncio
import base64
import io
import logging
import os
import time
import uuid
import wave
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("sonivox")

app = FastAPI(title="SONIVOX Voice Platform")

TTS_API = os.getenv(
    "TTS_API_URL",
    "https://michsethowusuwfp3--africa-tts-api-api.us-east.modal.run",
).rstrip("/")
API_SECRET = os.getenv("ULTRON_VOICE_SECRET", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
VOICE_BUCKET = "sonivox-voices"


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    voice_id: str
    lang: str = "eng"


class LegacySpeechRequest(BaseModel):
    text: str
    lang: str = "eng"


def get_voice_path() -> str:
    return os.getenv("VOICE_REFERENCE_PATH", "/etc/secrets/ultron_reference.b64")


def supabase_headers(token: str) -> dict:
    return {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {token}",
    }


async def get_authenticated_user(client: httpx.AsyncClient, token: str) -> dict:
    if not SUPABASE_URL or not SUPABASE_PUBLISHABLE_KEY:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    response = await client.get(
        f"{SUPABASE_URL}/auth/v1/user",
        headers=supabase_headers(token),
    )
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return response.json()


@app.get("/")
async def home():
    return FileResponse("web/index.html")


@app.get("/auth/callback")
async def auth_callback_page():
    return FileResponse("web/auth-callback.html")


@app.get("/signin")
async def sign_in_page():
    return FileResponse("web/signin.html")


@app.get("/signup")
async def sign_up_page():
    return FileResponse("web/signup.html")


@app.get("/reset-password")
async def reset_password_page():
    return FileResponse("web/reset-password.html")


@app.get("/api/config")
async def public_config():
    if not SUPABASE_URL or not SUPABASE_PUBLISHABLE_KEY:
        return {"configured": False}
    return {
        "configured": True,
        "supabase_url": SUPABASE_URL,
        "publishable_key": SUPABASE_PUBLISHABLE_KEY,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "product": "sonivox"}


@app.get("/health/ready")
async def readiness():
    voice_path = get_voice_path()
    return {
        "status": "ready" if SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY else "degraded",
        "supabase_configured": bool(SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY),
        "legacy_voice_reference_configured": os.path.isfile(voice_path),
    }


@app.post("/api/speech")
async def generate_speech(data: SpeechRequest, authorization: str = Header(default="")):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to generate speech")
    token = authorization.split(" ", 1)[1].strip()
    text = data.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Enter some text first")
    if data.lang not in {"eng", "yor", "hau", "ibo", "ful"}:
        raise HTTPException(status_code=400, detail="Unsupported language")

    timeout = httpx.Timeout(connect=15.0, read=100.0, write=45.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        user = await get_authenticated_user(client, token)
        user_id = user["id"]

        voice_response = await client.get(
            f"{SUPABASE_URL}/rest/v1/sonivox_voices",
            params={"id": f"eq.{data.voice_id}", "user_id": f"eq.{user_id}",
                    "select": "id,name,sample_path", "limit": "1"},
            headers={**supabase_headers(token), "Accept": "application/json"},
        )
        if voice_response.status_code != 200:
            raise HTTPException(status_code=502, detail="Could not load your voice profile")
        voices = voice_response.json()
        if not voices:
            raise HTTPException(status_code=404, detail="Voice profile not found")
        sample_path = voices[0]["sample_path"]
        if not sample_path.startswith(f"{user_id}/") or ".." in sample_path.split("/"):
            raise HTTPException(status_code=403, detail="Invalid voice sample path")

        sample_response = await client.get(
            f"{SUPABASE_URL}/storage/v1/object/authenticated/{VOICE_BUCKET}/{quote(sample_path, safe='/')}",
            headers=supabase_headers(token),
        )
        if sample_response.status_code != 200:
            raise HTTPException(status_code=404, detail="Your voice sample could not be loaded")
        voice_b64 = base64.b64encode(sample_response.content).decode("ascii")

        started = time.monotonic()
        try:
            tts_response = await client.post(
                f"{TTS_API}/v1/tts",
                json={
                    "text": text,
                    "lang": data.lang,
                    "format": "wav",
                    "voice_wav_base64": voice_b64,
                },
            )
            if tts_response.status_code == 429:
                raise HTTPException(status_code=503, detail="Voice provider is busy. Try again shortly.")
            tts_response.raise_for_status()
        except HTTPException:
            raise
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail="Speech generation timed out") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning("TTS provider returned HTTP %s", exc.response.status_code)
            raise HTTPException(status_code=502, detail="Voice provider could not generate this audio") from exc
        except httpx.RequestError as exc:
            logger.warning("TTS provider connection failed: %s", type(exc).__name__)
            raise HTTPException(status_code=502, detail="Could not reach the voice provider") from exc

        audio = tts_response.content
        if not audio.startswith(b"RIFF"):
            raise HTTPException(status_code=502, detail="Voice provider returned invalid WAV audio")

        duration_ms = None
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav:
                duration_ms = int(wav.getnframes() / wav.getframerate() * 1000)
        except (wave.Error, ZeroDivisionError):
            pass

        generation_id = str(uuid.uuid4())
        audio_path = f"{user_id}/generations/{generation_id}.wav"
        upload_response = await client.post(
            f"{SUPABASE_URL}/storage/v1/object/{VOICE_BUCKET}/{quote(audio_path, safe='/')}",
            headers={
                **supabase_headers(token),
                "Content-Type": "audio/wav",
                "x-upsert": "false",
            },
            content=audio,
        )
        if upload_response.status_code not in (200, 201):
            logger.error("Could not store generated audio: HTTP %s", upload_response.status_code)
            raise HTTPException(status_code=502, detail="Audio was generated but could not be saved")

        generation_response = await client.post(
            f"{SUPABASE_URL}/rest/v1/sonivox_generations",
            headers={
                **supabase_headers(token),
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json={
                "id": generation_id,
                "user_id": user_id,
                "voice_id": data.voice_id,
                "input_text": text,
                "status": "completed",
                "audio_path": audio_path,
                "duration_ms": duration_ms,
            },
        )
        if generation_response.status_code not in (200, 201):
            logger.error("Could not save generation record: HTTP %s", generation_response.status_code)
            raise HTTPException(status_code=502, detail="Audio was generated but history could not be saved")

        logger.info("SONIVOX generated audio in %.2fs for user %s", time.monotonic() - started, user_id)
        return {"id": generation_id, "audio_path": audio_path, "duration_ms": duration_ms}


# Legacy ULTRON endpoint retained for existing integrations.
@app.post("/speak")
async def speak(data: LegacySpeechRequest, x_api_key: str = Header(default="")):
    if not API_SECRET or x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    text = data.text.strip()
    if not text or len(text) > 2000:
        raise HTTPException(status_code=400, detail="Text must be 1–2000 characters")
    voice_path = get_voice_path()
    if not os.path.isfile(voice_path):
        raise HTTPException(status_code=503, detail="Voice reference is not configured")
    try:
        with open(voice_path, "r", encoding="utf-8") as audio_file:
            voice_b64 = audio_file.read().strip()
    except OSError as exc:
        logger.exception("Could not read legacy voice reference")
        raise HTTPException(status_code=503, detail="Voice reference could not be read") from exc
    if not voice_b64:
        raise HTTPException(status_code=503, detail="Voice reference is empty")
    payload = {"text": text, "lang": data.lang, "format": "wav", "voice_wav_base64": voice_b64}
    timeout = httpx.Timeout(connect=15.0, read=85.0, write=30.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for attempt in range(2):
            try:
                result = await client.post(f"{TTS_API}/v1/tts", json=payload)
                if result.status_code in (500, 502, 503, 504) and attempt == 0:
                    await asyncio.sleep(1.0)
                    continue
                if result.status_code == 429:
                    raise HTTPException(status_code=503, detail="TTS provider is rate-limiting requests")
                result.raise_for_status()
                if not result.content.startswith(b"RIFF"):
                    raise HTTPException(status_code=502, detail="TTS provider returned invalid audio")
                return Response(content=result.content, media_type="audio/wav")
            except httpx.HTTPStatusError as exc:
                if attempt == 0 and exc.response.status_code in (500, 502, 503, 504):
                    await asyncio.sleep(1.0)
                    continue
                raise HTTPException(status_code=502, detail=f"TTS provider returned HTTP {exc.response.status_code}") from exc
            except httpx.TimeoutException as exc:
                raise HTTPException(status_code=504, detail="TTS provider timed out") from exc
            except httpx.RequestError as exc:
                raise HTTPException(status_code=502, detail="Could not reach TTS provider") from exc
    raise HTTPException(status_code=502, detail="TTS provider failed after retry")


app.mount("/assets", StaticFiles(directory="web/assets"), name="assets")
