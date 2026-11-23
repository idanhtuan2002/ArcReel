# Assembly acceptance record

One section per milestone of the [assembly plan](../ASSEMBLY_PLAN.md): what was checked, the evidence, the verdict.

## M0 — DramaClaw up — ACCEPTED 2026-11-23

- Stack: `assembly/deploy/dramaclaw/up.sh` (DramaClaw `b299bfd` own `docker-compose.release.yml` + our override),
  project `assembly-dramaclaw`; images `claymorelab/dramaclaw:2.0.2` (4.64 GB), `dramaclaw-frontend:2.0.2`,
  `dramaclaw-gateway:v1.0.0-rc.24-dramaclaw.1`.
- `docker compose ps`: api (healthy) `127.0.0.1:8780`, newapi (healthy) `127.0.0.1:3000`, web `127.0.0.1:8080` —
  loopback only.
- `GET /api/v1/projects` → 200; web `/` → 200; NewAPI `/api/status` answers.
- `POST /api/v1/model-gateway/custom/newapi/init` → `ok`, mode `custom`, relay token `dramaclaw-ce-runtime` created;
  root password in `~/assembly-data/secrets/newapi-root` (600).
- Merged compose config shows `INDEXTTS2_PROVIDER=fal`, `INDEXTTS2_FAL_ENDPOINT=http://host.docker.internal:23350/…`,
  `host.docker.internal=host-gateway` on the api service.
- Disk after pull: 16 GB free on `/`.

## M1a — Vietnamese voice path — transport verified 2026-11-23

- Service: `assembly/deploy/voice-adapter.service` (user unit `voice-adapter`, active), listening on `172.17.0.1:23350`
  (docker0; DramaClaw's container resolves `host.docker.internal` to `172.17.0.1`).
- Probe: a 3.68 s WAV sample made by the VieNeu shim with preset "Ngọc Huyền" registered by SHA-256; from **inside**
  `assembly-dramaclaw-api-1`, the fal request `{"audio_url": "data:audio/wav;base64,…", "prompt": "Bác ơi, bác còn sửa
  đồng hồ cơ không ạ?"}` to `http://host.docker.internal:23350/fal-ai/index-tts-2/text-to-speech` returned
  `{"audio": {"url": "http://host.docker.internal:23350/audio/<id>.mp3"}}`; the container downloaded it: MP3, 2.48 s.
- Unit tests: `tests/unit/assembly/` 9 passed; ruff, basedpyright, deptry, test audit clean.
- Not yet verified: DramaClaw's own TTS task using a character voice sample uploaded through its API (M2).

## M1.0 — model probes through NewAPI — 2026-11-23

Keys pasted by the sponsor in DramaClaw "My Config" with `assembly/config/dramaclaw-profile.json`; DramaClaw created NewAPI
channels 1 `DC-openrouter` (type 20), 2 `DC-gemini` (24), 3 `DC-volcengine` (45, base `https://ark.ap-southeast.bytepluses.com`).
Calls with DramaClaw's own relay token on `127.0.0.1:3000`:

| Slot | Result |
|---|---|
| Text `DC-*-LLM` → OpenRouter `baidu/ernie-5.5-flash-preview:free` | first call 429 (upstream shared pool `tpm_rate_limit_exceeded`); retry 200, natural Vietnamese sentence |
| Vision → Gemini `gemini-3.5-flash` | 503 "high demand" twice, then channel test success in 38 s; `gemini-3.5-flash-lite` 1.0 s and `gemini-2.5-flash` 1.6 s succeed (fallback candidates); `gemini-2.5-flash-lite` 404 for new users |
| Embedding → Gemini `gemini-embedding-001` (768) | success 0.45 s |
| Image `LingShan-G2` → Seedream 4.5 via **VolcEngine type** channel, `/v1/images/generations` | 200, 1440×2560 (`m1-probes/seedream-text2img.jpg`); default output carries an "AI generated" mark; the Vietnamese prompt "đồng hồ quả quýt" was drawn literally as a tangerine clock |
| Image with **base64 reference** (`image: ["data:image/jpeg;base64,…"]`), `watermark: false` | 200, reference kept, no mark (`m1-probes/seedream-ref-base64.jpg`) |
| DramaClaw's own reference path `/v1/images/edits` JSON, `width`/`height`, base64 reference | 200, 1440×2560 |

Decisions from the probes:
- Image route = the VolcEngine-type channel (plan D7's OpenAI-type route is not needed; the `byteplus_openai` channel holds
  the key in DramaClaw but has no NewAPI channel).
- `watermark: false` set as a request-schema default on `LingShan-G2`, `LingShan-NB-2`, `seedance-1.0-pro-fast`; verified
  with DramaClaw's own `apply_media_request_schema` and in its saved mappings.
- D28: Seedream accepts base64 references, so the inline relay is viable for images; the ComfyUI first-frame half is still
  to probe with the Wan channel.
