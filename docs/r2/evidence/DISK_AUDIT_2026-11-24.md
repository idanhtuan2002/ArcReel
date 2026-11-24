# Disk audit 2026-11-24

Root `/` 195 G, 90 % (21 G free); drive D 277 G, 94 % (18 G free). NewAPI refuses requests above 95 % disk.
Measured with `du`/`docker system df -v`; usage checked against `docs/r2/ASSEMBLY_MODELS.md`, `assembly/`, the old
app's production project files (`~/arcreel-v2-staging/data/*/project.json`) and running services.

## Candidates (nothing deleted without the sponsor's choice)

| # | Item | Disk | Size | Used by | Recoverable |
|---|---|---|---|---|---|
| 1 | Ollama models not referenced anywhere: `gemma3:12b` 8.2, `kiwi_kiwi/qwen3.8-uncensored:9b` 6.4, `qwen3-vl:8b` 6.2, `minicpm-v:8b` 5.5 | D | 26.3 G | none found (assembly uses cloud models; old-app production uses `gemma3:4b`, `qwen2.5vl:7b`, `qwen3.5-vimax:9b`) | `ollama pull` |
| 2 | `ace-step-cache/uv` (package download cache of the ACE-Step music install) | D | 21 G | install only | re-download on reinstall |
| 3 | `operations/clef` (Cloudflare clef GGUF + llama runtime, reviewer experiment) | D | 8.3 G | none (reviewer gate removed 2026-11-23) | re-download |
| 4 | Old reviewer corpora (`operations/reviewer-corpus-*`) | D | 4.6 G | none | no (generated data) |
| 5 | 7 orphan Docker volumes (no container) | root | 6.7 G | none | no |
| 6 | 5 stopped containers (admiring_franklin, crazy_almeida, m6-pg18-test, arcreel-m9b-disposable-20261019, r18-arcreel-postgres) | root | small; frees images `infra-postgres`, searxng | none | no |
| 7 | `~/.codex/worktrees` + `~/.codex/sessions` | root | 4.8 G | old Codex sessions | no |
| 8 | Browser caches (Cốc Cốc, Chrome) | root | 2.1 G | cache | yes |

## Kept (in use or not ours)

- Ollama `gemma3:4b`, `qwen2.5vl:7b`, `qwen3.5-vimax:9b`, `bge-m3` (old-app production / embeddings).
- ComfyUI models 29 G (Wan for assembly), whisper 2.9 G, mmaudio 14 G, ace-step 18 G + hf 12 G, faceid 1.3 G, media 3.6 G.
- `infra_pios2_pgbackrest_repo` 10.7 G and other PIOS data — another project.
- Personal folders on D (`luu tru drive` 54 G, `python` 16 G, …) — not touched.
