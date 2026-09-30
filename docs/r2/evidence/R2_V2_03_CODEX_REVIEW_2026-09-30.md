# V2-03 ComfyUI backport: independent Codex review, 2026-09-30

- **Job:** `task-munsby0q-iy0z7h`
- **Reviewed head:** `88b39633f233de86486be3d98c0837fff3a0067e`
- **Base:** `r2-v2/main` (`2b1623fe`)
- **Round:** 1 (single round)

The verdict below is transcribed verbatim.

## 1. HEAD reviewed

`88b39633f233de86486be3d98c0837fff3a0067e` on `impl/r2-v2-03-comfyui`; base `r2-v2/main` resolves to `2b1623fe`. The worktree was clean at the final check.

## 2. Verdict

**ACCEPTED** for this independent code review. I found no concrete Blocker, Major, or Minor failure scenario in the reviewed paths. This is a static verdict; fresh tests could not start in the read-only sandbox.

## 3. Findings

| Severity | File:line | Failure scenario | Confidence |
|---|---|---|---|
| — | — | No qualifying defect found. | — |

## 4. Review questions

1. **Security:** ComfyUI generation and resume use guarded clients ([video backend](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/custom_provider/comfyui_backend.py:102), [image backend](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/custom_provider/comfyui_image_backend.py:114)); remote stop and the connectivity probe do too ([execution](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/custom_provider/comfyui_execution.py:245), [probe](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/server/routers/custom_providers.py:1252)). The shared client checks each request, including redirect hops ([guard](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/artifact_download_guard.py:117)). Upload, submit, poll, and cancel use the scoped request helper; `/view` uses scoped streaming ([client](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/custom_provider/comfyui_client.py:330)). Cross-origin redirects clear credentials **and** `json/files/data`; no surviving `current_json` assignment appears in that path ([redirect helper](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/video_backends/base.py:842)). The validator rejects `{{api_key}}` outside `auth` ([validator](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/custom_provider/comfyui/validator.py:330)).

2. **Admission and budget:** `custom-*` remains `custom_media`, and backend assembly checks current qualification ([paid routes](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/r2/host_hardening/paid_routes.py:143), [assembler](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/backend_assembly/assembler.py:82)). Trial-run admission precedes dispatch ([trial run](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/custom_provider/endpoint_test/trial_run.py:302)). Generation and trial runs enter `Ledger.record`, which reserves before yielding to the provider; the estimate has the `MIN_RESERVATION` floor ([media generator](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/media_generator.py:1027), [trial run](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/custom_provider/endpoint_test/trial_run.py:446), [ledger](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/ledger.py:145), [budget guard](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/budget_guard.py:83)). Explicit capacity columns win over the ComfyUI default of one per lane ([capacity table](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/generation_worker.py:239)).

3. **M7 authority:** The five named files’ diffs are confined to the listed failure encoding, capacity projection, provenance, warnings, and fixed-duration handling. The video path still records `api_call_id` before submission and retains its `execution_id` handling ([media generator](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/media_generator.py:1027), [generation tasks](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/server/services/generation_tasks.py:2823)). I found no added task state, lane, or execution path.

4. **Conflict resolutions:** The fork’s credential/body redirect rule is preserved after the donor’s `_Body` change; the plaintext credentials GET remains absent. The prompt splitter recognizes the fork’s Chinese negative-tail prefixes ([prompt utilities](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/prompt_utils.py:32)). Cancellation settles a trial run as failed ([trial run](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/custom_provider/endpoint_test/trial_run.py:389)). Direct JSON comparison found all six shared ComfyUI/declarative schema `$defs` equal. I checked the cited donor and fork commits with `git show`; no concrete dropped-behavior failure emerged from the representative resolutions.

5. **Declarative no-regression:** Kind dispatch retains the declarative validator ([validator](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/lib/custom_provider/endpoint_definition/validator.py:161)); the settings UI still selects declarative definitions separately from ComfyUI ([EndpointsSection](/home/anhtuan/content-production-os/.worktrees/r2-v2-03/frontend/src/components/pages/settings/endpoints/EndpointsSection.tsx:187)). Existing preview, validation, and trial-run paths remain present. Runtime equivalence is limited by the test restriction below.

## 5. Commands and results

- `git status`, `git rev-parse`, `git diff`, `git log`, `git show`, `rg`, and direct source reads: completed; final HEAD matched and worktree was clean.
- Shared `$defs` JSON comparison: six of six equal.
- `git diff --check r2-v2/main..HEAD`: one blank line at EOF in `ComfyuiEndpointDetail.tsx`; no concrete behavior failure.
- Requested targeted pytest command: **could not start**. `uv` returned `Read-only file system (os error 30)` while creating a `/tmp` directory. The ledger’s 5,834 passed / 1 skipped result is historical evidence at `a4c4dbe3`, not a fresh run at this HEAD.

## 6. Coverage limits

The codebase graph was approval blocked, so verification used source and diff inspection. No provider calls, network access, or full suite were run, as requested. Fresh targeted tests were blocked by the read-only filesystem. The verdict does not claim live ComfyUI behavior or a fresh runtime pass at `88b39633`.

## 7. JSON

```json
{
  "schema_version": 1,
  "status": "V2_03_IMPLEMENTATION_ACCEPTED",
  "accepted_candidate_head": "88b39633f233de86486be3d98c0837fff3a0067e",
  "reviewer": "codex",
  "reviewed_at": "2026-09-30T07:35:00Z",
  "required_skips": [
    "Fresh targeted pytest could not start: uv could not create a temporary directory on the read-only filesystem.",
    "Full suite, network, and provider calls were excluded by the review instructions."
  ],
  "material_unknowns": [
    "Runtime behavior at the reviewed HEAD was not freshly tested.",
    "No live ComfyUI server was exercised."
  ]
}
```
