# SONIVOX Human Expression Engine — Technical Plan

**Status:** Planning / audit complete  
**Product area:** Voice Studio only  
**Out of scope:** Singing Studio and its model, routes, quotas, generation history, and deployment.

## 1. Objective

Add expressive, non-verbal vocal events to ordinary SONIVOX text-to-speech while preserving the selected voice profile and keeping existing integrations compatible.

The authoring format will be **SONIVOX Vocal Expression Markup (SVEM)**: square-bracket commands embedded at the exact position where the sound should occur.

Example:

```text
[hmm] Let me think about that. [sigh]
[cough] Excuse me.
[breath] I have something important to tell you.
```

Commands are instructions, not text to pronounce.

## 2. Production baseline found in the repository

The current production backend is a FastAPI gateway in `main.py`.

- Developer endpoint: `POST /v1/speech`.
- Request model: `SpeechRequest` with `text` (1–1000 characters), optional `voice_id`, and `lang`.
- Developer authentication: Bearer SONIVOX API key, validated against the Supabase API-key records.
- Voice selection: user-owned voice profile and private stored reference sample; preset-bound API keys are supported.
- Upstream provider: configured by `TTS_API_URL`, defaulting to the existing Africa TTS Modal endpoint.
- Current upstream request: `POST {TTS_API}/v1/tts` with `text`, `lang`, `format: wav`, and `voice_wav_base64`.
- The gateway validates WAV output, stores generated audio, records generation history, and reserves/finalizes character usage.
- Authenticated dashboard speech generation uses a separate `POST /api/speech` flow.
- Singing generation is implemented separately at `POST /api/singing` and must not be modified as part of this project.
- The current root README documents only the legacy `/speak` route, so developer documentation needs a proper refresh as part of the release.

### What the audit does and does not establish

The gateway code proves that the current provider receives text and a reference voice sample. It does **not** establish that the upstream model supports coughs, sighs, humming, laughter, SSML, emotion controls, or voice-consistent non-speech audio. The provider's model identity, public capability documentation, and expressive controls remain unverified. Do not claim native expression support until it has been tested.

## 3. SVEM v1 command proposal

Initial event commands:

| Command | Meaning |
|---|---|
| `[breath]` | Natural inhale/exhale event |
| `[sigh]` | Sigh |
| `[cough]` | Cough |
| `[throat_clear]` | Throat clearing |
| `[hum]` | Non-lexical humming |
| `[hmm]` | Thoughtful vocalisation |
| `[umm]` | Hesitation vocalisation |
| `[laugh]` | Laughter |
| `[chuckle]` | Quiet laughter |
| `[gasp]` | Sudden intake of breath |
| `[yawn]` | Yawn |
| `[cry]` | Crying/sobbing |

V1 should treat these as **point events** inserted between speech segments. Commands that alter delivery over a span (for example whispering) need a separately designed paired-marker or structured-span syntax; do not implement ambiguous one-way state changes in the first parser.

Future syntax such as `[sigh:deep]` may be considered after the base command set and validation rules are stable.

## 4. Proposed processing architecture

1. **Request validation:** enforce the existing text and authentication limits.
2. **SVEM parser:** scan input once, producing ordered text segments and typed expression events with source offsets.
3. **Validation:** accept only documented commands; reject malformed or unknown commands with a clear 400 response (or a documented warning mode if later introduced). Never silently speak bracket instructions.
4. **Speech generation:** send only ordinary text segments to the configured TTS provider, using the selected user's voice reference.
5. **Expression rendering:** choose and evaluate the best available expression renderer:
   - First evaluate whether the current TTS provider can natively produce these events while conditioning on the same reference voice.
   - If not, benchmark a voice-conditioned expression model.
   - If neither produces sufficiently consistent results, use licensed/consented expression recordings as a fallback, clearly acknowledging that they may not perfectly match the cloned voice.
6. **Audio assembly:** resample to a common format, align segments in source order, apply controlled pauses/crossfades and loudness matching, and produce one validated WAV.
7. **Existing persistence and accounting:** reuse the existing storage/history path. Define billable characters from spoken text rather than markup syntax; do not let tags inflate or bypass quotas. Keep the current speech quota policy unless a product decision explicitly changes it.

Do not add a new model dependency or GPU service until comparative tests justify it. Cache reusable non-personal assets where licensing permits. Do not cache user-specific voice output across accounts.

## 5. API compatibility proposal

Extend `POST /v1/speech` with optional, backward-compatible fields rather than replacing the endpoint:

```json
{
  "text": "[hmm] Let me think about that. [sigh]",
  "voice_id": "voice_123",
  "lang": "eng",
  "expression_mode": "manual"
}
```

Proposed modes:

- `off`: current behaviour; bracket-like text is handled according to the documented literal-text/escaping rule.
- `manual`: render only explicit SVEM commands.
- `automatic`: allow the expression planner to add context-appropriate events, subject to user/developer controls and predictable limits.

For the first release, ship `off` and `manual` only if the rendering pipeline is production quality. Add `automatic` only after evaluation demonstrates that it does not insert distracting or inappropriate sounds.

The same optional configuration can later be exposed in the authenticated dashboard `/api/speech` route. Keep its session authentication, ownership checks, storage flow, and usage reservation intact.

### Compatibility requirements

- Existing requests with only `text`, `voice_id`, and `lang` must continue to work unchanged.
- Existing response fields and WAV response/storage conventions must remain stable.
- `/speak` remains untouched.
- `/api/singing`, its Hugging Face integration, and singing history remain untouched.
- Preset restrictions and API-key ownership rules must still apply.
- Add explicit maximum command count, total audio duration, and expression-event limits to prevent abuse and runaway processing.

## 6. LLM and developer integration package

API docs alone do not teach an LLM the markup. Release all of the following together:

1. **SVEM command reference:** canonical names, definitions, examples, placement rules, and error behaviour.
2. **LLM system-prompt snippet:** instructs a model when to use expressions, when not to use them, and to emit only supported commands.
3. **Structured tool definition:** lets compatible function-calling models discover supported expression actions and descriptions.
4. **SDK helpers:** Python and JavaScript helpers for request construction and optionally parsing/validating markup before submission.
5. **Quickstarts:** cURL, Python, JavaScript, and one generic LLM-agent integration example.

The LLM chooses the performance instructions; SONIVOX remains responsible for validating and rendering them.

## 7. Quality and safety requirements

- Preserve event order and exact placement relative to speech.
- Do not pronounce valid markup commands.
- Do not let unknown tags disappear silently.
- Match expression timbre to the selected voice where the model permits; disclose limitations where it does not.
- Avoid repetitive, excessive, or contextually inappropriate expressions.
- Keep expression volume and transitions natural without obscuring words.
- Require voice ownership or explicit permission for cloned voices and expression assets.
- Use properly licensed or consented recordings/models.
- Keep voice samples, generated audio, and provider credentials private.
- Ensure errors refund/release any reserved usage and do not leave partial generation records.

## 8. Implementation phases and exit criteria

### Phase 1 — Provider capability verification
Obtain provider/model identity and documentation; test plain speech, supported controls, and whether reference audio conditions non-speech sounds. Record latency, audio quality, and limitations.

**Exit:** a reproducible capability report and a chosen rendering strategy.

### Phase 2 — SVEM specification and parser
Implement a pure parser with source offsets, ordered segments, allowlisted commands, escaping/literal handling, and unit tests.

**Exit:** parser tests cover adjacent tags, tags at start/end, multiple tags, punctuation, Unicode, unknown tags, malformed tags, and literal bracket text.

### Phase 3 — Expression renderer prototype
Benchmark native provider support, voice-conditioned models, and consented asset fallback using the same test voice and prompts.

**Exit:** listening evaluation confirms acceptable realism, voice match, latency, and cost for the first supported commands.

### Phase 4 — Audio assembler
Implement format normalization, ordering, silence/pause handling, loudness matching, crossfades, duration validation, and WAV integrity checks.

**Exit:** assembled files play correctly with no missing, reordered, clipped, or overlapping events.

### Phase 5 — API and dashboard integration
Add optional request fields and integrate through a shared speech-generation service without changing authentication, ownership, storage, or billing invariants.

**Exit:** existing speech tests pass; manual SVEM requests produce valid audio; singing tests remain unchanged.

### Phase 6 — Documentation and SDK
Publish the canonical SVEM reference, LLM instructions, structured tool definition, and Python/JavaScript examples. Update README and OpenAPI descriptions.

**Exit:** a developer can follow a quickstart without private implementation knowledge.

### Phase 7 — Release hardening
Run regression, load, abuse-limit, tenant-isolation, consent, and listening tests; monitor failure rates and generation cost.

**Exit:** production release checklist signed off.

## 9. Test corpus

Use a fixed, consented reference voice and a repeatable corpus covering:

- Plain speech with no markup (regression baseline).
- Each supported expression individually.
- Expressions at the beginning, middle, and end of text.
- Consecutive events and events between clauses.
- Short and long speech segments.
- Multiple supported languages where the renderer supports them.
- Different voice profiles to measure voice consistency.
- Unknown, malformed, escaped, and excessive commands.

Score intelligibility, naturalness, voice similarity, event correctness, timing, clipping, latency, and per-request cost.

## 10. Immediate next actions

1. Identify the actual upstream TTS model/provider and obtain authoritative docs or source access.
2. Run controlled tests against the existing provider; do not infer capabilities from the gateway payload.
3. Select a renderer based on voice similarity and sound quality, not just availability.
4. Finalise SVEM v1 syntax and error semantics.
5. Implement the parser independently before connecting any new model.

**Current status:** repository audit completed at the gateway level; upstream expressive capabilities remain unverified. No production code, database schema, environment variables, or deployment settings have been changed by this planning work.
