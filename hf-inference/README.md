---
title: SONIVOX 9jaLingo Voice Inference
emoji: 🎙️
colorFrom: indigo
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# SONIVOX — private African voice-cloning inference

Private backend for SONIVOX. It loads `9jaLingo/9jaLingo-TTS-African-ckpt-25k` directly from the Hugging Face Hub and exposes an authenticated `POST /v1/clone` endpoint.

## Model and runtime

- Model: [9jaLingo/9jaLingo-TTS-African-ckpt-25k](https://huggingface.co/9jaLingo/9jaLingo-TTS-African-ckpt-25k)
- Inference: [9jaLingo Spark-TTS implementation](https://github.com/9jaLingo/9jalingo-Spark-tts) + [SparkVox](https://github.com/SparkAudio/SparkVox)
- Languages: Yoruba (yo), Hausa (ha), Igbo (ig), Nigerian Pidgin (pcm)
- Voice cloning uses a user-provided reference recording.
- The model card recommends a GPU with about 10 GB VRAM; CPU mode is only suitable for smoke tests and may be very slow.

## Required Space secrets

Set `SONIVOX_INFERENCE_TOKEN` to a long random secret. Set the same value as Render's `HF_TTS_INFERENCE_TOKEN`. Do not commit either value.

Optional variables:
- `HF_MODEL_ID` (defaults to the model above)
- `HF_MODEL_DIR` (defaults to `/data/models/9jalingo-african-tts`)

Attach persistent storage at `/data` if available so the downloaded weights survive restarts.

## API

`GET /health` reports service and model readiness.

`POST /v1/clone` accepts multipart fields:
- `text`: text to speak (up to 1,000 characters; split internally into short utterances)
- `language`: `yo`, `ha`, `ig`, or `pcm`
- `reference_audio`: WAV, FLAC, or OGG file

Authorization: `Bearer <SONIVOX_INFERENCE_TOKEN>`

Returns a WAV audio response. This endpoint is intended for SONIVOX's server only, not direct browser use.

## Hardware and cost

A GPU Space is required for production latency. Selecting paid GPU hardware can incur Hugging Face charges. Do not enable paid hardware without confirming the cost and attaching a billing method intentionally.
