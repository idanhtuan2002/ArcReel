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
