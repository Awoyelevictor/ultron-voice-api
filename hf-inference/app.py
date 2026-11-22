import hmac
import io
import logging
import os
import re
import sys
import tempfile
import threading
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from huggingface_hub import snapshot_download

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("sonivox-hf-inference")

MODEL_ID = os.getenv("HF_MODEL_ID", "9jaLingo/9jaLingo-TTS-African-ckpt-25k")
MODEL_DIR = Path(os.getenv("HF_MODEL_DIR", "/data/models/9jalingo-african-tts"))
SPARKVOX_DIR = Path(os.getenv("SPARKVOX_DIR", "/opt/SparkVox"))
TTS_SOURCE_DIR = Path(os.getenv("TTS_SOURCE_DIR", "/opt/9jalingo-Spark-tts"))
INFERENCE_TOKEN = os.getenv("SONIVOX_INFERENCE_TOKEN", "").strip()
SUPPORTED_LANGUAGES = {"yo", "ha", "ig", "pcm"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MODEL_LOCK = threading.Lock()
MODEL = None

app = FastAPI(title="SONIVOX Hugging Face Voice Inference", version="1.0.0")


def load_model():
    global MODEL
    if MODEL is not None:
        return MODEL
    with MODEL_LOCK:
        if MODEL is not None:
            return MODEL
        if not torch.cuda.is_available():
            logger.warning("CUDA is unavailable. CPU inference is supported for testing but may be extremely slow.")
        if not MODEL_DIR.exists() or not (MODEL_DIR / "BiCodec" / "model.safetensors").exists():
            logger.info("Downloading model %s from Hugging Face Hub", MODEL_ID)
            MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
            snapshot_download(repo_id=MODEL_ID, local_dir=str(MODEL_DIR))
        sys.path.insert(0, str(SPARKVOX_DIR))
        sys.path.insert(0, str(TTS_SOURCE_DIR))
        from src.inference import NaijaLingoTTS
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        logger.info("Loading 9jaLingo Spark-TTS model on %s", device)
        MODEL = NaijaLingoTTS(
            model_dir=str(MODEL_DIR),
            sparkvox_dir=str(SPARKVOX_DIR),
            device=device,
        )
        logger.info("9jaLingo model is ready")
        return MODEL


def split_text(text: str, max_words: int = 25) -> list[str]:
    """Keep requests within the model card's short-utterance guidance."""
    words = text.split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]


@app.get("/health")
def health():
    return {
        "status": "ok",
        "engine": "9jalingo-spark-tts",
        "model": MODEL_ID,
        "model_loaded": MODEL is not None,
        "cuda_available": torch.cuda.is_available(),
    }


@app.post("/v1/clone")
async def clone_voice(
    text: str = Form(..., min_length=1, max_length=1000),
    language: str = Form(...),
    reference_audio: UploadFile = File(...),
    authorization: str = Header(default=""),
):
    if not INFERENCE_TOKEN:
        raise HTTPException(status_code=503, detail="Inference service authentication is not configured.")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, INFERENCE_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized inference request.")
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Supported languages: yo, ha, ig, pcm.")
    clean_text = re.sub(r"\s+", " ", text).strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Text cannot be empty.")

    raw_audio = await reference_audio.read(MAX_UPLOAD_BYTES + 1)
    if not raw_audio or len(raw_audio) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Reference audio is empty or exceeds the 20 MB limit.")
    try:
        try:
            audio_array, sample_rate = sf.read(io.BytesIO(raw_audio), dtype="float32", always_2d=False)
        except Exception:
            # Browser uploads may be MP3/M4A/WebM; ffmpeg normalizes those to WAV.
            decoded = subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                 "-i", "pipe:0", "-f", "wav", "-ac", "1", "pipe:1"],
                input=raw_audio, capture_output=True, check=True, timeout=30,
            ).stdout
            audio_array, sample_rate = sf.read(io.BytesIO(decoded), dtype="float32", always_2d=False)
        if audio_array.size == 0 or sample_rate < 8000 or sample_rate > 96000:
            raise ValueError("Unsupported audio sample rate or empty audio")
        if audio_array.ndim > 1:
            audio_array = np.mean(audio_array, axis=1)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Upload a valid audio recording (WAV, FLAC, OGG, MP3, M4A, or WebM).") from exc

    engine = load_model()
    output_segments = []
    silence = np.zeros(int(engine.sample_rate * 0.12), dtype=np.float32)
    chunks = split_text(clean_text)
    with tempfile.NamedTemporaryFile(suffix=".wav") as reference_file:
        sf.write(reference_file.name, audio_array, sample_rate, subtype="PCM_16")
        try:
            for chunk in chunks:
                generated = engine.clone(chunk, reference_audio=reference_file.name)
                generated = np.asarray(generated, dtype=np.float32).squeeze()
                if generated.size == 0 or not np.isfinite(generated).all() or float(np.max(np.abs(generated))) < 1e-5:
                    raise RuntimeError("The model returned empty or silent audio.")
                output_segments.append(generated)
        except Exception as exc:
            logger.exception("Voice cloning failed")
            raise HTTPException(status_code=502, detail="The voice model failed to generate speech.") from exc

    combined = []
    for index, segment in enumerate(output_segments):
        if index:
            combined.append(silence)
        combined.append(segment)
    audio = np.concatenate(combined)
    buffer = io.BytesIO()
    sf.write(buffer, audio, engine.sample_rate, format="WAV", subtype="PCM_16")
    return Response(
        content=buffer.getvalue(),
        media_type="audio/wav",
        headers={"X-Audio-Sample-Rate": str(engine.sample_rate), "X-Model-Id": MODEL_ID},
    )
