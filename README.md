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

## Incremental speech for live AI responses

Existing `POST /v1/speech` remains unchanged and continues to generate a complete,
stored audio file. For live AI integrations, use `POST /v1/speech/chunk` once a
sentence-sized piece of the LLM response is ready.

- Authentication: `Authorization: Bearer YOUR_SONIVOX_API_KEY`
- JSON body: `{"text":"The next sentence.","lang":"eng","voice_id":"YOUR_VOICE_ID"}`
- Response: independently playable `audio/wav` bytes (not a JSON audio URL).
- Each successful chunk is counted against the character allowance.
- Chunk audio is returned directly; it is not added to generation history or object storage.
- Keep requests in response order and play each WAV as soon as it arrives. While chunk N
  plays, request chunk N+1. Do not wait for the complete LLM response before requesting
  the first chunk.

Recommended client pipeline:

1. Consume the LLM's streaming text output.
2. Buffer tokens until a sentence boundary (or roughly 120–220 characters).
3. Send that text to `/v1/speech/chunk`.
4. Queue the returned WAV for immediate playback.
5. Continue generating and queueing later chunks; stop and discard queued chunks if the user cancels.

The endpoint generates one complete WAV per text chunk. It does not claim to stream
partial waveform frames from the underlying speech model. The latency improvement comes
from starting TTS before the LLM has finished its full answer and overlapping generation
with playback.
