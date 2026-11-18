import asyncio
import base64
import io
import hashlib
import logging
import os
import time
import tempfile
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
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
VOICE_BUCKET = "sonivox-voices"
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
SINGING_SPACE = "phoenix1406/sonivox-vocal-studio"


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    voice_id: str | None = None
    lang: str = "eng"


class SingingRequest(BaseModel):
    lyrics: str = Field(min_length=1, max_length=3000)
    voice_id: str
    style: str = "Natural and emotional"
    custom_style: str = Field(default="", max_length=500)


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
        "developer_api_configured": bool(SUPABASE_SECRET_KEY),
        "legacy_voice_reference_configured": os.path.isfile(voice_path),
    }


@app.get("/api/usage")
async def get_usage(authorization: str = Header(default="")):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to view usage")
    token = authorization.split(" ", 1)[1].strip()
    async with httpx.AsyncClient(timeout=20.0) as client:
        user = await get_authenticated_user(client, token)
        period_start = time.strftime("%Y-%m-01", time.gmtime())
        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/sonivox_usage_periods",
            params={"user_id": f"eq.{user['id']}", "period_start": f"eq.{period_start}",
                    "select": "characters_used", "limit": "1"},
            headers={**supabase_headers(token), "Accept": "application/json"},
        )
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail="Could not load usage balance")
        rows = response.json()
        used = int(rows[0]["characters_used"]) if rows else 0
        return {"plan": "Free", "monthly_limit": 20000, "used": used,
                "remaining": max(0, 20000 - used), "billing_enabled": False}


def admin_headers() -> dict:
    if not SUPABASE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Developer API is not configured yet")
    return {"apikey": SUPABASE_SECRET_KEY}


async def get_api_key_owner(client: httpx.AsyncClient, raw_key: str) -> tuple[dict, dict]:
    if not raw_key.startswith("svx_live_") or len(raw_key) < 40:
        raise HTTPException(status_code=401, detail="Invalid API key")
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    response = await client.get(
        f"{SUPABASE_URL}/rest/v1/sonivox_api_keys",
        params={"key_hash": f"eq.{digest}", "revoked_at": "is.null",
                "select": "id,user_id,name,preset_id", "limit": "1"},
        headers={**admin_headers(), "Accept": "application/json"},
    )
    if response.status_code != 200:
        logger.error("API key lookup failed: HTTP %s", response.status_code)
        raise HTTPException(status_code=503, detail="Could not validate API key")
    rows = response.json()
    if not rows:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    key_row = rows[0]
    await client.patch(
        f"{SUPABASE_URL}/rest/v1/sonivox_api_keys",
        params={"id": f"eq.{key_row['id']}"},
        headers={**admin_headers(), "Content-Type": "application/json"},
        json={"last_used_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
    )
    return key_row, admin_headers()


@app.get("/v1/voices")
async def developer_list_voices(authorization: str = Header(default="")):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Provide your SONIVOX API key as a Bearer token")
    raw_key = authorization.split(" ", 1)[1].strip()
    async with httpx.AsyncClient(timeout=20.0) as client:
        key_row, headers = await get_api_key_owner(client, raw_key)
        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/sonivox_voices",
            params={"user_id": f"eq.{key_row['user_id']}",
                    "select": "id,name,created_at", "order": "created_at.desc"},
            headers={**headers, "Accept": "application/json"},
        )
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail="Could not load voice profiles")
        return {"voices": response.json()}


@app.post("/v1/speech")
async def developer_generate_speech(data: SpeechRequest, authorization: str = Header(default="")):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Provide your SONIVOX API key as a Bearer token")
    raw_key = authorization.split(" ", 1)[1].strip()
    text = data.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Enter some text first")
    if data.lang not in {"eng", "yor", "hau", "ibo", "ful"}:
        raise HTTPException(status_code=400, detail="Unsupported language")
    timeout = httpx.Timeout(connect=15.0, read=100.0, write=45.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        key_row, headers = await get_api_key_owner(client, raw_key)
        user_id = key_row["user_id"]
        preset = None
        voice_id = data.voice_id
        if key_row.get("preset_id"):
            preset_response = await client.get(
                f"{SUPABASE_URL}/rest/v1/sonivox_voice_presets",
                params={"id": f"eq.{key_row['preset_id']}", "user_id": f"eq.{user_id}",
                        "select": "id,name,voice_id,settings,allow_overrides", "limit": "1"},
                headers={**headers, "Accept": "application/json"},
            )
            presets = preset_response.json() if preset_response.status_code == 200 else []
            if not presets:
                raise HTTPException(status_code=409, detail="The voice preset linked to this API key is unavailable")
            preset = presets[0]
            if voice_id and not preset["allow_overrides"]:
                raise HTTPException(status_code=403, detail="This API key is locked to its selected voice preset")
            if not voice_id or not preset["allow_overrides"]:
                voice_id = preset["voice_id"]
        elif not voice_id:
            raise HTTPException(status_code=400, detail="This legacy API key requires voice_id. Create a preset-bound key for preset-based requests.")
        voice_response = await client.get(
            f"{SUPABASE_URL}/rest/v1/sonivox_voices",
            params={"id": f"eq.{voice_id}", "user_id": f"eq.{user_id}",
                    "select": "id,sample_path", "limit": "1"},
            headers={**headers, "Accept": "application/json"},
        )
        voices = voice_response.json() if voice_response.status_code == 200 else []
        if not voices:
            raise HTTPException(status_code=404, detail="Voice profile not found for this API account")
        sample_path = voices[0]["sample_path"]
        if not sample_path.startswith(f"{user_id}/") or ".." in sample_path.split("/"):
            raise HTTPException(status_code=403, detail="Invalid voice sample path")
        sample_response = await client.get(
            f"{SUPABASE_URL}/storage/v1/object/{VOICE_BUCKET}/{quote(sample_path, safe='/')}",
            headers=headers,
        )
        if sample_response.status_code != 200:
            raise HTTPException(status_code=404, detail="Voice sample could not be loaded")
        voice_b64 = base64.b64encode(sample_response.content).decode("ascii")
        reservation_id = str(uuid.uuid4())
        reserve = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/reserve_sonivox_characters_for_user",
            headers={**headers, "Content-Type": "application/json"},
            json={"p_user_id": user_id, "p_request_id": reservation_id, "p_characters": len(text)},
        )
        if reserve.status_code != 200:
            logger.error("Developer API reservation failed: HTTP %s", reserve.status_code)
            raise HTTPException(status_code=503, detail="Could not verify monthly usage")
        if not reserve.json().get("allowed"):
            raise HTTPException(status_code=402, detail="Monthly free character allowance exhausted")
        try:
            tts = await client.post(
                f"{TTS_API}/v1/tts",
                json={"text": text, "lang": data.lang, "format": "wav",
                      "voice_wav_base64": voice_b64},
            )
            if tts.status_code == 429:
                raise HTTPException(status_code=503, detail="Voice provider is busy; retry shortly")
            tts.raise_for_status()
            audio = tts.content
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
            upload = await client.post(
                f"{SUPABASE_URL}/storage/v1/object/{VOICE_BUCKET}/{quote(audio_path, safe='/')}",
                headers={**headers, "Content-Type": "audio/wav", "x-upsert": "false"},
                content=audio,
            )
            if upload.status_code not in (200, 201):
                raise HTTPException(status_code=502, detail="Generated audio could not be stored")
            history = await client.post(
                f"{SUPABASE_URL}/rest/v1/sonivox_generations",
                headers={**headers, "Content-Type": "application/json"},
                json={"id": generation_id, "user_id": user_id, "voice_id": voice_id,
                      "input_text": text, "status": "completed", "audio_path": audio_path,
                      "duration_ms": duration_ms},
            )
            if history.status_code not in (200, 201):
                raise HTTPException(status_code=502, detail="Could not save generation history")
            signed = await client.post(
                f"{SUPABASE_URL}/storage/v1/object/sign/{VOICE_BUCKET}/{quote(audio_path, safe='/')}",
                headers={**headers, "Content-Type": "application/json"},
                json={"expiresIn": 3600},
            )
            signed.raise_for_status()
            signed_data = signed.json()
            audio_url = signed_data.get("signedURL") or signed_data.get("signedUrl")
            if not audio_url:
                raise HTTPException(status_code=502, detail="Could not create a temporary audio link")
            if audio_url.startswith("/"):
                audio_url = SUPABASE_URL + "/storage/v1" + audio_url
            finish = await client.post(
                f"{SUPABASE_URL}/rest/v1/rpc/finish_sonivox_reservation_for_user",
                headers={**headers, "Content-Type": "application/json"},
                json={"p_user_id": user_id, "p_request_id": reservation_id, "p_success": True},
            )
            if finish.status_code != 200:
                raise HTTPException(status_code=502, detail="Could not finalize usage reservation")
            return {"id": generation_id, "audio_url": audio_url,
                    "audio_path": audio_path, "duration_ms": duration_ms,
                    "characters_used": len(text), "preset": preset["name"] if preset else None}
        except Exception:
            try:
                await client.post(
                    f"{SUPABASE_URL}/rest/v1/rpc/finish_sonivox_reservation_for_user",
                    headers={**headers, "Content-Type": "application/json"},
                    json={"p_user_id": user_id, "p_request_id": reservation_id, "p_success": False},
                )
            except Exception:
                logger.exception("Could not refund failed developer API reservation")
            raise




def run_singing_model(reference_bytes, lyrics, style, custom_style):
    from gradio_client import Client, handle_file

    with tempfile.TemporaryDirectory(prefix="sonivox-singing-") as folder:
        reference_path = os.path.join(folder, "reference.wav")
        with open(reference_path, "wb") as f:
            f.write(reference_bytes)

        client = Client(SINGING_SPACE, hf_token=HF_TOKEN)
        result = client.predict(
            reference=handle_file(reference_path),
            lyrics=lyrics,
            style=style,
            custom_style=custom_style,
            api_name="/generate_song",
        )

        if isinstance(result, (list, tuple)):
            result = result[0] if result else None
        if isinstance(result, dict):
            result = result.get("path") or result.get("name")

        if not isinstance(result, str) or not os.path.isfile(result):
            raise RuntimeError("Singing model returned no audio file.")

        with open(result, "rb") as f:
            audio = f.read()

        if not audio.startswith(b"RIFF"):
            raise RuntimeError("Singing model did not return a WAV file.")

        return audio


@app.post("/api/singing")
async def generate_singing(
    data: SingingRequest,
    authorization: str = Header(default="")
):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in first.")
    if not HF_TOKEN:
        raise HTTPException(status_code=503, detail="Singing Studio is not configured.")

    token = authorization.split(" ", 1)[1].strip()
    lyrics = data.lyrics.strip()
    if not lyrics:
        raise HTTPException(status_code=400, detail="Enter your lyrics.")

    allowed_styles = {
        "Natural and emotional", "Smooth R&B", "Gospel solo",
        "Afrobeats vocal style", "Soft pop", "Soulful ballad",
    }
    if data.style not in allowed_styles:
        raise HTTPException(status_code=400, detail="Unsupported vocal style.")

    timeout = httpx.Timeout(connect=20, read=240, write=60, pool=20)

    async with httpx.AsyncClient(timeout=timeout) as client:
        user = await get_authenticated_user(client, token)
        user_id = user["id"]

        voice_response = await client.get(
            f"{SUPABASE_URL}/rest/v1/sonivox_voices",
            params={
                "id": f"eq.{data.voice_id}",
                "user_id": f"eq.{user_id}",
                "select": "id,name,sample_path",
                "limit": "1",
            },
            headers=supabase_headers(token),
        )
        if voice_response.status_code != 200:
            raise HTTPException(status_code=502, detail="Could not load voice profile.")

        voices = voice_response.json()
        if not voices:
            raise HTTPException(status_code=404, detail="Voice profile not found.")

        sample_path = voices[0]["sample_path"]
        if not sample_path.startswith(f"{user_id}/") or ".." in sample_path.split("/"):
            raise HTTPException(status_code=403, detail="Invalid voice sample path.")

        sample = await client.get(
            f"{SUPABASE_URL}/storage/v1/object/authenticated/"
            f"{VOICE_BUCKET}/{quote(sample_path, safe='/')}",
            headers=supabase_headers(token),
        )
        if sample.status_code != 200:
            raise HTTPException(status_code=404, detail="Could not load voice recording.")

        try:
            audio = await asyncio.to_thread(
                run_singing_model,
                sample.content,
                lyrics,
                data.style,
                data.custom_style.strip(),
            )
        except Exception as exc:
            logger.exception("Singing generation failed")
            raise HTTPException(
                status_code=502,
                detail="Singing generation failed. Check the Hugging Face Space.",
            ) from exc

        duration_ms = None
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav:
                duration_ms = int(wav.getnframes() / wav.getframerate() * 1000)
        except (wave.Error, ZeroDivisionError):
            pass

        generation_id = str(uuid.uuid4())
        audio_path = f"{user_id}/generations/{generation_id}.wav"

        upload = await client.post(
            f"{SUPABASE_URL}/storage/v1/object/"
            f"{VOICE_BUCKET}/{quote(audio_path, safe='/')}",
            headers={
                **supabase_headers(token),
                "Content-Type": "audio/wav",
                "x-upsert": "false",
            },
            content=audio,
        )
        if upload.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail="Could not save generated vocals.")

        history = await client.post(
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
                "input_text": lyrics,
                "generation_type": "singing",
                "status": "completed",
                "audio_path": audio_path,
                "duration_ms": duration_ms,
            },
        )
        if history.status_code not in (200, 201):
            logger.error("Singing history insert failed: HTTP %s", history.status_code)
            raise HTTPException(status_code=502, detail="Vocals saved, but history failed.")

        return {
            "id": generation_id,
            "audio_path": audio_path,
            "duration_ms": duration_ms,
            "type": "singing",
        }

@app.post("/api/speech")
async def generate_speech(data: SpeechRequest, authorization: str = Header(default="")):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to generate speech")
    if not data.voice_id:
        raise HTTPException(status_code=400, detail="Select a voice profile first")
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

        reservation_id = str(uuid.uuid4())
        reserve_response = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/reserve_sonivox_characters",
            headers={**supabase_headers(token), "Content-Type": "application/json"},
            json={"p_request_id": reservation_id, "p_characters": len(text)},
        )
        if reserve_response.status_code != 200:
            logger.error("Usage reservation failed: HTTP %s", reserve_response.status_code)
            raise HTTPException(status_code=502, detail="Could not verify your free usage balance")
        reservation = reserve_response.json()
        if not reservation.get("allowed"):
            raise HTTPException(status_code=402, detail="Monthly free allowance used. Your balance resets at the start of next month.")

        try:
            started = time.monotonic()
            try:
                tts_response = await client.post(
                    f"{TTS_API}/v1/tts",
                    json={"text": text, "lang": data.lang, "format": "wav",
                          "voice_wav_base64": voice_b64},
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
                headers={**supabase_headers(token), "Content-Type": "audio/wav", "x-upsert": "false"},
                content=audio,
            )
            if upload_response.status_code not in (200, 201):
                logger.error("Could not store generated audio: HTTP %s", upload_response.status_code)
                raise HTTPException(status_code=502, detail="Audio was generated but could not be saved")

            generation_response = await client.post(
                f"{SUPABASE_URL}/rest/v1/sonivox_generations",
                headers={**supabase_headers(token), "Content-Type": "application/json",
                         "Prefer": "return=representation"},
                json={"id": generation_id, "user_id": user_id, "voice_id": data.voice_id,
                      "input_text": text, "status": "completed", "audio_path": audio_path,
                      "duration_ms": duration_ms},
            )
            if generation_response.status_code not in (200, 201):
                logger.error("Could not save generation record: HTTP %s", generation_response.status_code)
                raise HTTPException(status_code=502, detail="Audio was generated but history could not be saved")

            finish_response = await client.post(
                f"{SUPABASE_URL}/rest/v1/rpc/finish_sonivox_reservation",
                headers={**supabase_headers(token), "Content-Type": "application/json"},
                json={"p_request_id": reservation_id, "p_success": True},
            )
            if finish_response.status_code != 200:
                logger.error("Could not finalize usage reservation: HTTP %s", finish_response.status_code)
                raise HTTPException(status_code=502, detail="Audio was created but usage could not be finalized")
            logger.info("SONIVOX generated audio in %.2fs for user %s", time.monotonic() - started, user_id)
            return {"id": generation_id, "audio_path": audio_path, "duration_ms": duration_ms}
        except Exception:
            try:
                await client.post(
                    f"{SUPABASE_URL}/rest/v1/rpc/finish_sonivox_reservation",
                    headers={**supabase_headers(token), "Content-Type": "application/json"},
                    json={"p_request_id": reservation_id, "p_success": False},
                )
            except Exception:
                logger.exception("Could not release failed usage reservation")
            raise


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


SONIVOX_ADMIN_USER_ID = os.getenv("SONIVOX_ADMIN_USER_ID", "").strip()
SONIVOX_ADMIN_EMAIL = "awoyeleemma1@gmail.com"


async def require_sonivox_admin(client: httpx.AsyncClient, authorization: str) -> dict:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.split(" ", 1)[1].strip()
    user = await get_authenticated_user(client, token)
    if not SONIVOX_ADMIN_USER_ID:
        logger.error("SONIVOX_ADMIN_USER_ID is not configured")
        raise HTTPException(status_code=503, detail="Admin access is not configured")
    if user.get("id") != SONIVOX_ADMIN_USER_ID:
        raise HTTPException(status_code=403, detail="This account is not authorized for SONIVOX administration")
    if (user.get("email") or "").lower() != SONIVOX_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Admin account verification failed")
    if not user.get("email_confirmed_at"):
        raise HTTPException(status_code=403, detail="Admin email must be confirmed")
    return user


@app.get("/admin")
async def admin_dashboard_page():
    return FileResponse("web/admin.html")


@app.get("/api/admin/overview")
async def admin_overview(authorization: str = Header(default="")):
    async with httpx.AsyncClient(timeout=20.0) as client:
        await require_sonivox_admin(client, authorization)
        headers = {**admin_headers(), "Prefer": "count=exact", "Range": "0-0", "Accept": "application/json"}
        user_count_response = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/sonivox_admin_registered_user_count",
            headers=admin_headers(),
            json={},
        )
        if user_count_response.status_code != 200:
            logger.error("Admin registered-user count failed: HTTP %s", user_count_response.status_code)
            raise HTTPException(status_code=502, detail="Could not load registered account count")
        try:
            registered_users = int(user_count_response.json())
        except (ValueError, TypeError):
            raise HTTPException(status_code=502, detail="Registered account count was unavailable")
        tables = {
            "voices": ("sonivox_voices", "id"),
            "generations": ("sonivox_generations", "id"),
            "api_keys": ("sonivox_api_keys", "id"),
        }
        counts = {"users": registered_users}
        for label, (table, count_column) in tables.items():
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/{table}",
                params={"select": count_column, "limit": "1"},
                headers=headers,
            )
            if response.status_code not in (200, 206):
                logger.error("Admin overview count failed for %s: HTTP %s", table, response.status_code)
                raise HTTPException(status_code=502, detail="Could not load platform statistics")
            content_range = response.headers.get("content-range", "")
            try:
                counts[label] = int(content_range.rsplit("/", 1)[1])
            except (ValueError, IndexError):
                raise HTTPException(status_code=502, detail="Statistics count was unavailable")
        return {"counts": counts, "free_monthly_character_limit": 20000,
                "billing_enabled": False, "admin_email": SONIVOX_ADMIN_EMAIL}


@app.get("/api/admin/keys")
async def admin_list_api_keys(authorization: str = Header(default="")):
    async with httpx.AsyncClient(timeout=20.0) as client:
        await require_sonivox_admin(client, authorization)
        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/sonivox_api_keys",
            params={"select": "id,user_id,name,key_prefix,created_at,last_used_at,revoked_at",
                    "order": "created_at.desc", "limit": "200"},
            headers={**admin_headers(), "Accept": "application/json"},
        )
        if response.status_code != 200:
            logger.error("Admin API-key listing failed: HTTP %s", response.status_code)
            raise HTTPException(status_code=502, detail="Could not load API key inventory")
        return {"keys": response.json()}


app.mount("/assets", StaticFiles(directory="web/assets"), name="assets")
