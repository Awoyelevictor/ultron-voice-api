# SONIVOX Voice API

SONIVOX is a FastAPI-powered speech-generation platform backed by Africa TTS. This repository contains the production server implementation.

- **Production:** https://sonivox.onrender.com
- **API reference:** [API.md](./API.md)
- **Interactive OpenAPI UI:** https://sonivox.onrender.com/docs
- **OpenAPI JSON:** https://sonivox.onrender.com/openapi.json

## Developer API at a glance

All developer API requests use an API key in the HTTP Bearer authorization header:

```http
Authorization: Bearer svx_live_YOUR_SECRET_KEY
```

Keep API keys on a trusted server. Do not embed them in browser JavaScript, mobile app bundles, public repositories, or client-side code.

| Method | Path | Purpose | Authentication |
|---|---|---|---|
| GET | `/health` | Basic service health | None |
| GET | `/health/ready` | Readiness/configuration indicators | None |
| GET | `/v1/voices` | List voices owned by the API-key account | Developer API key |
| POST | `/v1/speech` | Generate speech and return a temporary audio URL | Developer API key |
| GET | `/api/usage` | Read signed-in user's monthly usage | Supabase access token |
| POST | `/api/speech` | Generate speech for a signed-in web user | Supabase access token |
| POST | `/api/voice/trim` | Upload and trim a voice recording | Supabase access token |
| POST | `/speak` | Legacy ULTRON WAV endpoint | Legacy `X-API-Key` |

See [API.md](./API.md) for request schemas, examples, responses, errors, and authentication details.

## Local development

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the server:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The server requires the relevant Supabase configuration and Hugging Face token for full functionality. See the deployment configuration in your private Render environment; never commit secrets.

## Render

Typical start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Build command:

```bash
pip install -r requirements.txt
```

## Security

- Never commit API keys, Supabase secret keys, Hugging Face tokens, or reference audio.
- Developer API keys are stored as SHA-256 hashes by the server.
- Use HTTPS for all production requests.
- Treat returned signed audio URLs as temporary bearer links; the current implementation creates links with a one-hour expiry.
