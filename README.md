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


## 9jaLingo voice cloning (preview branch)

The SONIVOX dashboard and developer speech endpoints use 9jaLingo's OpenAI-compatible voice-cloning model. Configure the following Render environment variable before testing:

- `NAIJALINGO_API_KEY` — API key generated from the 9jaLingo developer dashboard.

The integration uses model `9jalingo-clone-1`, passes the user's stored reference audio as a hex-encoded `reference_audio`, requests WAV output, and maps SONIVOX language values to the provider codes:

- `yor` → `yo` (Yoruba)
- `hau` → `ha` (Hausa)
- `ibo` → `ig` (Igbo)
- `pcm` → `pcm` (Nigerian Pidgin)

The legacy `/speak` endpoint remains on its existing Africa TTS configuration for compatibility. Do not switch the production service until a live 9jaLingo key has been configured and real cloned WAV output has passed smoke tests.
