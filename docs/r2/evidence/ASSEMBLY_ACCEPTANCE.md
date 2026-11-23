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
