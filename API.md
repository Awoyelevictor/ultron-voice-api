# SONIVOX Developer API v1

This document describes the developer-facing API implemented by the SONIVOX production server.

- **Base URL:** `https://sonivox.onrender.com`
- **Production source branch:** `sonivox-mvp-ui`
- **OpenAPI UI:** [https://sonivox.onrender.com/docs](https://sonivox.onrender.com/docs)
- **OpenAPI JSON:** [https://sonivox.onrender.com/openapi.json](https://sonivox.onrender.com/openapi.json)

> This reference is based on the FastAPI route and model definitions in `main.py`. The live OpenAPI document should be treated as the runtime schema authority if it differs from this manually maintained guide.

## Authentication

The `/v1/*` developer endpoints require a SONIVOX developer API key in the HTTP Authorization header:

```http
Authorization: Bearer svx_live_YOUR_SECRET_KEY
```

The server checks that the key begins with `svx_live_`, validates its stored hash, and rejects invalid or revoked keys.

**Keep the key secret.** Make API calls from a trusted backend. Never ship a developer key in browser JavaScript, a mobile application, or a public repository.

The web-app endpoints under `/api/*` use a Supabase user access token instead; they are not authenticated with developer API keys.

## Endpoints

### 1. Health check

`GET /health`

No authentication required.

Example:

```bash
curl https://sonivox.onrender.com/health
```

Response:

```json
{
  "status": "ok",
  "product": "sonivox"
}
```

### 2. Readiness information

`GET /health/ready`

No authentication required. Reports whether key integrations are configured; it does not perform a full speech-generation test.

Example response:

```json
{
  "status": "ready",
  "supabase_configured": true,
  "developer_api_configured": true,
  "legacy_voice_reference_configured": false,
  "africa_tts_configured": true
}
```

The booleans above are illustrative; actual values depend on the deployed environment.

### 3. List saved voice profiles

`GET /v1/voices`

Requires a developer API key.

Example:

```bash
curl https://sonivox.onrender.com/v1/voices \
  -H "Authorization: Bearer svx_live_YOUR_SECRET_KEY"
```

Response shape:

```json
{
  "voices": [
    {
      "id": "VOICE_UUID",
      "name": "My Narrator",
      "created_at": "2026-01-15T12:00:00+00:00"
    }
  ]
}
```

Only voice profiles belonging to the API key's owner are returned. The `id` is the `voice_id` used for speech generation.

### 4. Generate speech

`POST /v1/speech`

Requires a developer API key. Request content type is `application/json`.

Headers:

```http
Authorization: Bearer svx_live_YOUR_SECRET_KEY
Content-Type: application/json
```

Request body:

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | Yes | Text to synthesize; 1–1,000 characters |
| `voice_id` | string or null | Conditional | ID of a saved voice profile |
| `lang` | string | No | Language code; defaults to `eng` |

A regular API key without a linked preset must provide `voice_id`. A preset-bound key can use its configured voice. If a preset disallows overrides, supplying a different `voice_id` returns HTTP 403.

Example:

```bash
curl -X POST https://sonivox.onrender.com/v1/speech \
  -H "Authorization: Bearer svx_live_YOUR_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello, welcome to SONIVOX.",
    "voice_id": "YOUR_VOICE_UUID",
    "lang": "eng"
  }'
```

Successful response shape:

```json
{
  "id": "GENERATION_UUID",
  "audio_url": "https://...temporary-signed-audio-link...",
  "audio_path": "USER_ID/generations/GENERATION_UUID.wav",
  "duration_ms": 3500,
  "characters_used": 27,
  "preset": null
}
```

The `audio_url` is a temporary signed URL generated with a 3,600-second (one-hour) expiry. Download or play the audio before it expires. The response contains a URL to the stored WAV audio; it does not return raw audio bytes directly.

### Supported language codes

The server currently accepts these exact values:

| Code | Language |
|---|---|
| `eng` | English |
| `yor` | Yoruba |
| `hau` | Hausa |
| `ibo` | Igbo |
| `twi` | Twi |
| `swh` | Swahili |
| `zul` | Zulu |
| `sna` | Shona |
| `ewe` | Ewe |
| `amh` | Amharic |

### 5. Check signed-in web-user usage

`GET /api/usage`

This is a web-app endpoint, not a developer-key endpoint. It requires the signed-in user's Supabase access token:

```http
Authorization: Bearer SUPABASE_USER_ACCESS_TOKEN
```

Response shape:

```json
{
  "plan": "Free",
  "monthly_limit": 20000,
  "used": 1250,
  "remaining": 18750,
  "billing_enabled": false
}
```

The current implementation reports a 20,000-character monthly free allowance and indicates billing is disabled. Usage is measured for the current UTC calendar month.

## Other web-app endpoints (not developer-key endpoints)

These routes are implemented for the SONIVOX website and use a Supabase user access token:

- `POST /api/speech` — generate speech for a signed-in user. JSON body uses `text`, `voice_id`, and `lang`. Returns generation metadata including `id`, `audio_path`, and `duration_ms`; unlike `/v1/speech`, this route does not return a signed `audio_url` in its response.
- `POST /api/voice/trim` — multipart form upload with fields `audio`, `start_seconds`, and `end_seconds`. Accepts source files up to 500 MB and selected segments up to 10 minutes. Returns `sample_path`, `duration_seconds`, and `size_bytes`.
- `GET /api/config` — returns public Supabase client configuration used by the web app.

## Legacy endpoint

`POST /speak` is retained for older ULTRON integrations. It uses the legacy `X-API-Key` header and returns raw WAV bytes (`audio/wav`). It is not the SONIVOX developer API v1.

## Error handling

The server uses FastAPI's standard error response shape:

```json
{
  "detail": "Human-readable error message"
}
```

Common statuses for `/v1/speech` and `/v1/voices`:

| HTTP status | Meaning |
|---|---|
| 400 | Invalid input, missing required voice ID for a legacy key, or unsupported language |
| 401 | Missing, invalid, or revoked developer API key |
| 402 | Monthly free character allowance exhausted |
| 403 | Preset or voice override is not permitted |
| 404 | Voice profile does not exist for this API account, or its sample cannot be loaded |
| 409 | Voice preset linked to the key is unavailable |
| 502 | Speech generation, storage, history, or signed-link operation failed |
| 503 | Developer API or required integration is not configured/available |
| 504 | Speech generation timed out |

Exact error messages are returned in the `detail` field.

## Usage accounting

The developer speech route reserves the requested text's character count before synthesis. A successful generation finalizes the reservation. If generation fails, the backend attempts to release/refund the reservation. The monthly allowance is currently 20,000 characters per user, as implemented by the server's usage reservation logic. Billing is currently disabled in the usage response.

## Integration recommendations

1. Store the API key in your server-side environment variables.
2. Call `GET /v1/voices` to obtain valid voice IDs for the key owner.
3. Call `POST /v1/speech` with text, voice ID, and language.
4. Fetch the returned `audio_url` promptly; it expires after one hour.
5. Handle non-2xx responses and read the JSON `detail` field.
6. Do not assume the legacy `/speak` response or authentication format applies to `/v1/*`.

## Source of truth

- [Production backend source: main.py](https://github.com/Awoyelevictor/ultron-voice-api/blob/sonivox-mvp-ui/main.py)
- [Interactive runtime API schema](https://sonivox.onrender.com/openapi.json)
