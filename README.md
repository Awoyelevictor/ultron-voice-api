# ULTRON Voice API

A lightweight FastAPI gateway that forwards speech requests to the AfriSpeech TTS endpoint using a privately stored reference voice.

## Endpoints

- `GET /` — service status
- `GET /health` — health check
- `POST /speak` — generate WAV speech (requires `X-API-Key`)

## Render configuration

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Environment variable: `ULTRON_VOICE_SECRET` (set a strong random value)
- Secret file: upload `ultron_reference.b64`; Render mounts it at `/etc/secrets/ultron_reference.b64`

Do not commit the reference audio, its Base64 representation, or API secrets.
