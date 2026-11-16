# ULTRON Voice Platform — Foundation Plan

## Product goal

Evolve the existing ULTRON Voice API into an open-source, multi-user voice platform. Each user can create an account, upload an authorised voice sample, create a private voice profile, generate personal API keys, synthesize speech with a selected voice, and integrate the service into their own applications.

The existing FastAPI gateway and Africa TTS upstream remain the starting point. The current single global reference voice and shared API secret are compatibility features only; they must not become the authorization model for multi-user accounts.

## Product principles

- Multi-tenant by default: every voice, API key, generation job, and usage record belongs to one user.
- Privacy by default: raw voice samples and generated audio are private; never expose storage URLs publicly.
- Consent-first cloning: users must confirm they own the voice or have explicit permission to clone it. Provide reporting and takedown procedures.
- Secret hygiene: show a newly generated API key once, store only a secure hash, support revocation and rotation, and never put provider secrets in browser code.
- Open-source core: document local development, self-hosting, environment variables, deployment, and API usage.
- Provider abstraction: keep the speech engine behind an adapter so Africa TTS can be replaced without rewriting accounts, voice management, or API-key logic.

## Proposed architecture

1. FastAPI application — REST API, authentication, voice management, API-key verification, speech generation, rate limiting, and OpenAPI documentation.
2. PostgreSQL — users, voice metadata, API-key hashes, generation history, usage counters, and audit events.
3. Private object storage — uploaded voice references and generated audio. Store object keys in the database, not public URLs.
4. TTS provider adapter — accepts a selected voice reference and text, calls the configured upstream provider, validates audio output, and returns WAV.
5. Web dashboard — signup/login, overview, voice library, clone flow, speech playground, API keys, usage, and docs.

The existing repository is currently a small FastAPI gateway. It does not yet include account registration, a database, per-user voice storage, or per-user API keys. Those are new platform capabilities.

## Initial data model

- users: identity and account status. Use a proven auth provider or securely hashed passwords; never store plaintext.
- voices: owner, display name, provider, private storage object key, language, status, consent attestation, created timestamp.
- api_keys: owner, key prefix, secure hash, scopes, last-used timestamp, expiry, revoked timestamp.
- generations: owner, voice, text metadata, output object key, duration/character count, status, created timestamp.
- usage_events: owner, API key, operation, billable units, timestamp.
- audit_events: security-sensitive account, voice, and key actions.

Every user-owned record must be checked against the authenticated owner on the server. Never trust a user_id supplied in a request body as proof of ownership.

## Initial API contract

### Accounts
- POST /v1/auth/signup
- POST /v1/auth/login
- POST /v1/auth/logout
- GET /v1/me

### Voice library
- POST /v1/voices — create a voice profile and upload its reference sample.
- GET /v1/voices — list only the authenticated user's voices.
- GET /v1/voices/{voice_id} — retrieve an owned voice.
- DELETE /v1/voices/{voice_id} — delete an owned voice and its private sample.

### Speech
- POST /v1/speech — synthesize text using an owned voice; return audio or a short-lived download URL.
- GET /v1/generations — list the authenticated user's generation history.

### Developer keys
- POST /v1/api-keys — create a key; return the raw key once.
- GET /v1/api-keys — list key metadata, never hashes or full secrets.
- DELETE /v1/api-keys/{key_id} — revoke a key.

### Operations
- GET /health
- GET /health/ready

The existing POST /speak endpoint should remain temporarily for ULTRON's current integration during migration. Mark it legacy; do not use it as the multi-user API contract.

## Voice-cloning workflow

1. User uploads MP3/WAV through an authenticated, size-limited upload flow.
2. Validate file type using inspected media content, duration, sample rate, and size; do not trust filename or browser MIME type.
3. Ask the user to attest that they own the voice or have permission to clone it.
4. Store the original sample in private object storage.
5. Create a voice profile and pass its reference to the TTS provider adapter when generating speech.
6. Report provider limitations clearly. A saved reference sample is not automatically a newly trained model; actual cloning quality and persistence depend on upstream engine capabilities.

## Security and abuse controls

- Enforce ownership checks on every voice, generation, and key operation.
- Use TLS, secure password handling, session expiry, CSRF protection where cookie sessions are used, and login throttling.
- Hash API keys; store a non-secret prefix for display.
- Apply per-key and per-account rate limits and character quotas.
- Restrict upload size, duration, and allowed audio formats; inspect and validate uploaded files.
- Keep provider credentials and database/storage secrets server-side.
- Log security events without logging passwords, full API keys, raw voice data, or full speech text.
- Add deletion workflows for voice samples and generated files.
- Require consent attestation and provide a reporting/takedown path to reduce impersonation and non-consensual cloning.

## Delivery phases

1. Foundation: choose and configure PostgreSQL, authentication, private object storage, migrations, and environment configuration.
2. Accounts and keys: signup/login, account identity, API-key generation/verification/revocation.
3. Voice library: secure uploads, per-user voice records, consent workflow, list/delete.
4. Speech API: provider adapter accepts a selected user's voice reference; preserve legacy /speak during migration.
5. Dashboard: account screens, voice library, cloning/upload flow, speech playground, key management, usage.
6. Developer experience: OpenAPI docs, quickstarts for cURL/Python/JavaScript, examples, self-hosting guide.
7. Hardening and release: tenant-isolation tests, abuse controls, quotas, backups, monitoring, license, contribution guide.

## Decisions required before implementing the account/storage layer

- Database and authentication provider (recommended: managed PostgreSQL plus a mature hosted auth service for the first hosted release).
- Private object storage provider and upload limits.
- Which TTS upstream endpoint and request format support passing a different voice reference per request, plus its audio duration/size limits.
- Whether the first hosted release is invitation-only or open registration.

Do not deploy a public multi-user service until authentication, tenant isolation, private storage, quotas, and consent controls are implemented and tested.