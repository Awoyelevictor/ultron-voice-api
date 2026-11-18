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


## 11. Phase 1 research update — 18 November 2026

### Confirmed architecture relationship

The public Africa TTS project states that it is built on Kyutai Pocket TTS, supports voice cloning from a short 3–10 second clip, and exposes text-generation APIs. Its public documentation does not list inline vocal-event tags or native cough/sigh/hum controls. This is consistent with the production gateway audit: the current API forwards text and a voice reference to the provider, but there is no documented expression-control field in the gateway contract.

### Strong research lead: Silencio-2

Silencio-2 is a Pocket TTS fine-tune that explicitly supports positional inline sound tags including `[laugh]`, `[sigh]`, `[gasp]`, `[cough]`, and `[clear_throat]`; it also supports short-reference voice cloning. Its model card reports English-only support and notes that tag strength varies between takes. It was trained by extending the Pocket TTS tokenizer/text table and fine-tuning on a custom dataset.

This is a promising proof-of-concept for SVEM, but it is **not a drop-in replacement for Africa TTS**:
- Silencio-2 is documented as English-only, while Africa TTS targets 92 African languages plus English.
- Both are in the Pocket TTS family, but shared ancestry does not prove tokenizer, checkpoint, phonemizer, language-front-end, or voice-embedding compatibility.
- We must test the same consenting reference voice, command positions, and target languages before selecting it.
- The public model card says the output can vary from take to take; important outputs require listening evaluation.

### Licensing gate

The Africa TTS repository states that its code is MIT-licensed but its model and default voices are CC-BY-NC-4.0. The Silencio-2 model card states CC-BY-4.0 for its weights and MIT for its adapted inference code. Before using either model or adapting weights in a commercial SONIVOX deployment, verify the complete license notices, upstream/base-model terms, training-data permissions, and any applicable restrictions. Do not assume the code license grants commercial rights to model weights or voice assets. Obtain qualified legal review if needed.

### Phase 1 preliminary conclusion

- **Africa TTS native inline expression support:** not documented; treat as unsupported until an endpoint test or provider confirmation proves otherwise.
- **Hybrid rendering around Africa TTS:** technically viable in principle; requires quality testing for voice match, timing, language coverage, and operating cost.
- **Pocket TTS-family expressive model:** Silencio-2 is a concrete research candidate for English proof-of-concept, not yet approved for production or multilingual use.
- **Commercial deployment:** model/voice licensing is a release gate, not an afterthought.

### Next verification tasks

1. Ask the Africa TTS provider/maintainer whether the deployed Modal endpoint supports any hidden or experimental event tokens and whether a tag-aware checkpoint exists.
2. Verify the exact production endpoint's package/model version and request schema; compare it with the public Africa TTS server implementation.
3. Run a controlled Silencio-2 test using a voice sample with permission and the same event prompts, then evaluate identity consistency and event realism.
4. Check license notices and upstream dependencies before any production adoption.
5. Decide whether to retain Africa TTS for multilingual spoken segments and route expression events to a separate renderer, or pursue a tag-aware multilingual fine-tune with properly licensed data.

**Status remains Phase 1.** No production code, model, database, environment variable, or deployment has been changed.


### Additional dataset lead: Basis Global Emotions

Silencio-2's notice identifies Basis Global Emotions as a development dataset. Its public dataset card describes 525.17 hours, 137,696 recordings, 10,420 speakers and 108 locales, including non-verbal cue examples such as sigh, breath, gasp, clear throat, yawn and cough. The dataset card states its Basis Data License permits commercial model training and commercial deployment, subject to its restrictions (including no redistribution of recordings and no speaker identification/impersonation).

This is a potentially valuable licensed data source for a future multilingual expression fine-tune. It is not evidence that we already have access to the dataset or that the current Africa TTS checkpoint can be commercially fine-tuned. Dataset access is request-based, and we must preserve its license terms and the separate model-weight terms.

### Revised technical recommendation

Run a two-track evaluation before selecting the final route:

- **Track A — Fast English proof-of-concept:** evaluate Silencio-2 on a permitted reference voice and compare its inline sound events, voice similarity, CPU latency and repeatability.
- **Track B — Africa TTS continuity / multilingual path:** obtain provider confirmation and evaluate whether a tag-aware version can be trained or adapted while preserving supported African languages. Resolve the Africa TTS checkpoint's CC-BY-NC-4.0 model restriction before commercial use; do not assume the MIT code license covers the weights.

Do not replace the production provider or merge either model into the production service during this evaluation.


## 12. Phase 1 verification update — 18 November 2026

### Silencio-2 interface verified from its public Space source

The public Hugging Face Space source confirms the model is used as a **complete English speech synthesizer**. Its synthesize function accepts text containing inline sound tags, an optional uploaded reference clip (up to 10 seconds), and returns one 24 kHz mono waveform. The Space supports [laugh], [sigh], [gasp], [cough], and [clear_throat]; it also supports emotion/delivery tags such as <happy>, <sad>, <angry>, <fear>, <surprised>, and <whisper>.

This changes the initial hybrid assumption:

- Silencio-2 is **not documented as an expression-only audio renderer**.
- Its documented path generates the spoken words and tagged vocal events together in one model pass.
- Therefore, do not split Africa TTS speech and Silencio-2 output and concatenate them as if Silencio-2 returned isolated cough/sigh clips. That could duplicate speech and create an audible voice/timbre discontinuity.
- The safer first prototype is **engine routing**: Africa TTS for the current multilingual path; Silencio-2 for English expressive requests, subject to reference-voice similarity and commercial licensing checks.
- True cross-engine event-only rendering remains a separate research task. It requires a validated method to generate isolated expressions in the same speaker identity and assemble them without artifacts.

### Test execution result

The Silencio-2 Space's parameter schema was inspected successfully. It supports an optional uploaded voice reference and deterministic seed selection. An inference attempt was made with a bundled test voice and a sentence containing [sigh] and [cough], but the Space rejected execution because its ZeroGPU quota was exhausted. **No audio was generated or evaluated in this run.** Do not report this as a successful listening test.

The exact production Modal endpoint's /openapi.json and /docs could not be retrieved through the available inspection route. The repository gateway source still confirms the outgoing request fields (text, lang, format: wav, voice_wav_base64), but the deployed provider version and any undocumented controls remain unverified.

### Licensing clarification

The current Silencio-2 model card and NOTICE identify CC-BY-4.0 weights and MIT inference code, and identify Basis Global Emotions as a development dataset. The Space source repeats the attribution requirement. This is more specific than a generic claim that the model is simply commercially cleared: review the full CC-BY terms, all upstream model notices, dataset terms, and any applicable obligations before commercial deployment. Africa TTS's published model/default-voice CC-BY-NC-4.0 restriction remains a separate and significant commercial-use blocker unless the deployed provider can establish a different license or permission.

### Revised Phase 1 decision

1. Keep the existing production Africa TTS route unchanged.
2. Treat Silencio-2 as an English expressive **alternative route**, not an expression-only add-on.
3. Do not combine the two waveforms until a separately validated event-only method exists.
4. Obtain the production provider's exact model/version/schema and licensing confirmation.
5. Retry Silencio-2 inference when Space compute is available, first with a bundled voice, then with a consented SONIVOX reference sample.
6. Compare plain and expressive output for voice similarity, intelligibility, event placement, repeatability, latency, and cost.
7. Do not start implementation or change production until the test results and licensing gate support a decision.

**Status remains Phase 1 — provider capability verification.** This update is documentation-only. No production code, database, secrets, Render configuration, model deployment, or Singing Studio component has been changed.
