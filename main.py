import asyncio
import base64
import io
import hashlib
import logging
import os
import tempfile
import threading
import time
import uuid
import wave
from urllib.parse import quote

import httpx
from gradio_client import Client, handle_file
from fastapi import FastAPI, Header, HTTPException, File, Form, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("sonivox")

app = FastAPI(title="SONIVOX Voice Platform")

HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
HF_SPACE_ID = "phoenix1406/sonivox-vocal-studio"
HF_CLIENT = None
HF_CLIENT_LOCK = threading.Lock()
AFRICA_LANGUAGES = {
    "eng": "English", "yor": "Yoruba", "hau": "Hausa", "ibo": "Igbo",
    "twi": "Twi", "swh": "Swahili", "zul": "Zulu", "sna": "Shona",
    "ewe": "Ewe", "amh": "Amharic",
}
API_SECRET = os.getenv("ULTRON_VOICE_SECRET", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
VOICE_BUCKET = "sonivox-voices"


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    voice_id: str | None = None
    lang: str = "eng"


class LegacySpeechRequest(BaseModel):
    text: str
    lang: str = "eng"




def inspect_generated_wav(audio: bytes) -> dict:
    """Validate the complete PCM WAV and reject empty or near-silent output."""
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise HTTPException(status_code=502, detail="Africa TTS returned an invalid WAV file")

    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            channels = wav.getnchannels()
            sample_rate = wav.getframerate()
            frame_count = wav.getnframes()
            sample_width = wav.getsampwidth()
            compression = wav.getcomptype()
            if not channels or channels > 2 or sample_rate < 8000 or sample_rate > 96000:
                raise wave.Error("Unsupported channel count or sample rate")
            if frame_count <= 0 or sample_width not in (1, 2, 3, 4) or compression != "NONE":
                raise wave.Error("Unsupported or empty PCM stream")
            frames = wav.readframes(frame_count)
            expected_bytes = frame_count * channels * sample_width
            if len(frames) != expected_bytes:
                raise wave.Error("Truncated PCM frame data")
    except (wave.Error, EOFError, OSError) as exc:
        logger.warning("Rejected malformed Africa TTS WAV: %s", str(exc)[:200])
        raise HTTPException(status_code=502, detail="Africa TTS returned an unreadable WAV file") from exc

    scale = float(1 << (sample_width * 8 - 1))
    peak = 0.0
    sum_squares = 0.0
    sample_count = 0
    for offset in range(0, len(frames), sample_width):
        raw = frames[offset:offset + sample_width]
        value = raw[0] - 128 if sample_width == 1 else int.from_bytes(raw, "little", signed=True)
        normalized = value / scale
        magnitude = abs(normalized)
        peak = max(peak, magnitude)
        sum_squares += normalized * normalized
        sample_count += 1

    rms = (sum_squares / sample_count) ** 0.5 if sample_count else 0.0
    duration_ms = int(frame_count / sample_rate * 1000)
    logger.info(
        "Africa TTS WAV validated: duration_ms=%s rate=%s channels=%s sample_width=%s bytes=%s peak=%.6f rms=%.6f",
        duration_ms, sample_rate, channels, sample_width, len(audio), peak, rms,
    )
    if duration_ms < 100 or peak < 0.0001 or rms < 0.00001:
        logger.error(
            "Rejected unusable Africa TTS audio: duration_ms=%s peak=%.7f rms=%.7f",
            duration_ms, peak, rms,
        )
        raise HTTPException(
            status_code=502,
            detail="Africa TTS returned silent or incomplete audio. Nothing was saved or charged; please retry.",
        )
    return {
        "duration_ms": duration_ms,
        "sample_rate": sample_rate,
        "channels": channels,
        "peak": peak,
        "rms": rms,
    }


def get_hf_client() -> Client:
    global HF_CLIENT
    if not HF_TOKEN:
        raise HTTPException(status_code=503, detail="Africa TTS is not configured. Add HF_TOKEN to the SONIVOX Render environment.")
    if HF_CLIENT is None:
        with HF_CLIENT_LOCK:
            if HF_CLIENT is None:
                try:
                    HF_CLIENT = Client(HF_SPACE_ID, token=HF_TOKEN, verbose=False, analytics_enabled=False)
                except Exception as exc:
                    logger.exception("Could not connect to the private Africa TTS Space")
                    raise HTTPException(status_code=502, detail="Could not connect to the Africa TTS service. Check the Hugging Face token and Space status.") from exc
    return HF_CLIENT


def prepare_africa_reference(reference_bytes: bytes) -> bytes:
    """Keep the saved voice profile intact, but send Africa TTS an 8-second WAV excerpt."""
    try:
        with wave.open(io.BytesIO(reference_bytes), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            if source.getcomptype() != "NONE" or sample_rate <= 0 or channels <= 0:
                raise wave.Error("Unsupported reference WAV format")
            duration = frame_count / sample_rate
            if duration < 3.0:
                raise HTTPException(
                    status_code=422,
                    detail="This voice sample is too short for Africa TTS. Use a sample at least 3 seconds long.",
                )
            selected_frames = min(frame_count, int(8.0 * sample_rate))
            selected_audio = source.readframes(selected_frames)
        prepared = io.BytesIO()
        with wave.open(prepared, "wb") as target:
            target.setnchannels(channels)
            target.setsampwidth(sample_width)
            target.setframerate(sample_rate)
            target.writeframes(selected_audio)
        if duration > 8.0:
            logger.info(
                "Prepared Africa TTS reference excerpt: original_duration=%.2fs selected_duration=%.2fs",
                duration, selected_frames / sample_rate,
            )
        else:
            logger.info("Africa TTS reference duration accepted: %.2fs", duration)
        return prepared.getvalue()
    except HTTPException:
        raise
    except (wave.Error, EOFError, OSError) as exc:
        logger.exception("Could not prepare the saved voice sample for Africa TTS")
        raise HTTPException(
            status_code=422,
            detail="The saved voice sample is not a readable WAV file. Please re-upload the voice sample.",
        ) from exc


def _generate_africa_audio(reference_bytes: bytes, text: str, lang: str) -> bytes:
    language_name = AFRICA_LANGUAGES.get(lang)
    if not language_name:
        raise HTTPException(status_code=400, detail="Unsupported language. Choose one of the ten Africa TTS languages.")
    reference_path = None
    try:
        # Africa TTS requires a 3–10 second speaker reference. Keep the full
        # user profile in storage, but pass only an 8-second excerpt to the model.
        reference_bytes = prepare_africa_reference(reference_bytes)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as reference_file:
            reference_file.write(reference_bytes)
            reference_path = reference_file.name
        client = get_hf_client()
        # The current Space callback is exposed by Gradio as the /lambda API.
        result = client.predict(handle_file(reference_path), text, language_name, api_name="/lambda")
        audio_result = result[0] if isinstance(result, (tuple, list)) else result
        if isinstance(audio_result, dict):
            audio_path = audio_result.get("path") or audio_result.get("name")
        else:
            audio_path = audio_result
        if not isinstance(audio_path, str) or not os.path.isfile(audio_path):
            raise RuntimeError("Africa TTS did not return a downloadable audio file")
        with open(audio_path, "rb") as generated_file:
            return generated_file.read()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Africa TTS Space generation failed")
        message = str(exc).lower()
        if "timeout" in message or "timed out" in message:
            raise HTTPException(status_code=504, detail="Africa TTS generation timed out. Please retry.") from exc
        if "401" in message or "403" in message or "unauthorized" in message:
            raise HTTPException(status_code=503, detail="Hugging Face could not authorize access to the private Africa TTS Space. Check HF_TOKEN.") from exc
        raise HTTPException(status_code=502, detail="Africa TTS could not generate speech. Check that the Hugging Face Space is running, then retry.") from exc
    finally:
        if reference_path and os.path.exists(reference_path):
            os.remove(reference_path)


async def generate_africa_audio(reference_bytes: bytes, text: str, lang: str) -> bytes:
    return await asyncio.to_thread(_generate_africa_audio, reference_bytes, text, lang)


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
        "africa_tts_configured": bool(HF_TOKEN),
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
    if data.lang not in AFRICA_LANGUAGES:
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
            audio = await generate_africa_audio(sample_response.content, text, data.lang)
            audio_info = inspect_generated_wav(audio)
            duration_ms = audio_info["duration_ms"]
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



MAX_VOICE_SOURCE_BYTES = 500 * 1024 * 1024


def _trim_uploaded_audio(source_file, start_seconds: float, end_seconds: float) -> bytes:
    """Seek into the uploaded source and export only the selected segment as 24 kHz mono PCM WAV."""
    try:
        import av
        import numpy as np
    except ImportError as exc:
        logger.exception("Server-side audio trimming dependencies are unavailable")
        raise HTTPException(status_code=503, detail="The audio trimming service is not ready. Please try again later.") from exc

    if start_seconds < 0 or end_seconds <= start_seconds or end_seconds - start_seconds > 600:
        raise HTTPException(status_code=400, detail="Select a segment between 1 second and 10 minutes.")
    output = io.BytesIO()
    try:
        with av.open(source_file) as container:
            audio_stream = next((stream for stream in container.streams if stream.type == "audio"), None)
            if audio_stream is None:
                raise HTTPException(status_code=400, detail="The uploaded file contains no audio track.")
            if container.duration and end_seconds > (container.duration / av.time_base) + 1:
                raise HTTPException(status_code=400, detail="The selected end time is beyond the recording duration.")
            container.seek(int(start_seconds / float(audio_stream.time_base)), stream=audio_stream, backward=True, any_frame=False)
            resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)
            with wave.open(output, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                written = 0
                for decoded in container.decode(audio_stream):
                    converted = resampler.resample(decoded)
                    for frame in converted:
                        if frame.pts is None or frame.time_base is None:
                            continue
                        frame_start = float(frame.pts * frame.time_base)
                        samples = frame.to_ndarray().reshape(-1)
                        left = max(0, int((start_seconds - frame_start) * 24000 + 0.999999))
                        right = min(len(samples), int((end_seconds - frame_start) * 24000 + 0.999999))
                        if right > left:
                            chunk = samples[left:right].astype(np.int16, copy=False).tobytes()
                            wav.writeframesraw(chunk)
                            written += right - left
                        if frame_start >= end_seconds:
                            break
                    if frame.time is not None and float(frame.time) >= end_seconds:
                        break
                for frame in resampler.resample(None):
                    if frame.pts is None or frame.time_base is None:
                        continue
                    frame_start = float(frame.pts * frame.time_base)
                    samples = frame.to_ndarray().reshape(-1)
                    left = max(0, int((start_seconds - frame_start) * 24000 + 0.999999))
                    right = min(len(samples), int((end_seconds - frame_start) * 24000 + 0.999999))
                    if right > left:
                        chunk = samples[left:right].astype(np.int16, copy=False).tobytes()
                        wav.writeframesraw(chunk)
                        written += right - left
                if written < 24000:
                    raise HTTPException(status_code=422, detail="The selected segment contains less than one second of readable audio.")
        return output.getvalue()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Server-side audio trim failed")
        raise HTTPException(status_code=422, detail="Could not decode this audio file. Try exporting it as MP3, M4A or WAV.") from exc


@app.post("/api/voice/trim")
async def trim_voice_sample(
    audio: UploadFile = File(...),
    start_seconds: float = Form(...),
    end_seconds: float = Form(...),
    authorization: str = Header(default=""),
):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to add a voice profile.")
    token = authorization.split(" ", 1)[1].strip()
    if not audio.filename:
        raise HTTPException(status_code=400, detail="Choose an audio file first.")
    try:
        audio.file.seek(0, os.SEEK_END)
        source_size = audio.file.tell()
        audio.file.seek(0)
        if source_size <= 0 or source_size > MAX_VOICE_SOURCE_BYTES:
            raise HTTPException(status_code=413, detail="The recording must be smaller than 500 MB.")
        if end_seconds <= start_seconds or end_seconds - start_seconds > 600:
            raise HTTPException(status_code=400, detail="Select no more than 10 minutes of audio.")
        async with httpx.AsyncClient(timeout=45.0) as client:
            user = await get_authenticated_user(client, token)
            user_id = user["id"]
            wav_bytes = await asyncio.to_thread(_trim_uploaded_audio, audio.file, start_seconds, end_seconds)
            sample_path = f"{user_id}/{uuid.uuid4()}.wav"
            upload_response = await client.post(
                f"{SUPABASE_URL}/storage/v1/object/{VOICE_BUCKET}/{quote(sample_path, safe='/')}",
                headers={**supabase_headers(token), "Content-Type": "audio/wav", "x-upsert": "false"},
                content=wav_bytes,
            )
            if upload_response.status_code not in (200, 201):
                logger.error("Trimmed voice sample upload failed: HTTP %s", upload_response.status_code)
                raise HTTPException(status_code=502, detail="The trimmed audio could not be saved to your private voice storage.")
            return {"sample_path": sample_path, "duration_seconds": round((end_seconds - start_seconds), 2),
                    "size_bytes": len(wav_bytes)}
    finally:
        await audio.close()


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
    if data.lang not in AFRICA_LANGUAGES:
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
            audio = await generate_africa_audio(sample_response.content, text, data.lang)
            audio_info = inspect_generated_wav(audio)
            duration_ms = audio_info["duration_ms"]

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
    try:
        reference_audio = base64.b64decode(voice_b64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Voice reference is not valid base64 audio") from exc
    audio = await generate_africa_audio(reference_audio, text, data.lang)
    inspect_generated_wav(audio)
    return Response(content=audio, media_type="audio/wav")


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
