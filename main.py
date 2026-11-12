import os
import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI(title="ULTRON Voice API")

TTS_API = "https://michsethowusuwfp3--africa-tts-api-api.us-east.modal.run"
API_SECRET = os.getenv("ULTRON_VOICE_SECRET", "")

class SpeechRequest(BaseModel):
    text: str
    lang: str = "eng"

@app.get("/")
async def home():
    return {"service": "ULTRON Voice API", "status": "online"}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/speak")
async def speak(data: SpeechRequest, x_api_key: str = Header(default="")):
    if not API_SECRET or x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not data.text.strip() or len(data.text) > 2000:
        raise HTTPException(status_code=400, detail="Text must be 1–2000 characters")

    voice_path = os.getenv(
        "VOICE_REFERENCE_PATH",
        "/etc/secrets/ultron_reference.b64"
    )

    if not os.path.exists(voice_path):
        raise HTTPException(status_code=503, detail="Voice reference is not configured")

    with open(voice_path, "r", encoding="utf-8") as audio_file:
        voice_b64 = audio_file.read().strip()

    payload = {
        "text": data.text,
        "lang": data.lang,
        "format": "wav",
        "voice_wav_base64": voice_b64
    }

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            result = await client.post(TTS_API + "/v1/tts", json=payload)
            result.raise_for_status()

        if not result.content.startswith(b"RIFF"):
            raise HTTPException(status_code=502, detail="TTS returned invalid audio")

        return Response(content=result.content, media_type="audio/wav")

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"TTS provider returned HTTP {exc.response.status_code}"
        )
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Could not reach TTS provider")
