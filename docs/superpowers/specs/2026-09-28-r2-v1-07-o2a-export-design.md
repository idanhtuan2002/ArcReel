# R2 V1-07 P1 — O2a export: Gate C approves the composed final, the export is its byte copy

Date: 2026-09-28. Branch `feat/r2-m7e-v1-lineage`. Decision: ADR-0090 (O2a) and its
2026-09-28 correction; research `docs/research/2026-09-28-r2-v1-export-definition.md`.
This spec implements that decision and adds no new authority: versions, the Artifact
Manifest, the R2 currency bridge, the Gate C/D routes and the download token stay the owners.

## Observed gaps (at `48908541`)

1. `FinalCutRenderedAssetRequest.tool` and `RenderedCutAsset.tool` are `Literal["remotion"]`;
   the deterministic `GoldenAComposer` produces an `ffmpeg` composite.
2. Gate C trusts the caller's `produced.sha256`; the server never hashes the file it stages.
3. Gate C records every candidate as a `ShotSpec` with caller-supplied dependencies, so a
   composite's lineage to the shot masters is whatever the caller claims.
4. Nothing writes the approved final to `output/`.
5. Gate D's `deliverable_digest` is a free string.
6. No single-file download exists for the finished video.

## Design

### Gate C for a `COMPOSITE` final (`POST /projects/{p}/gates/final-cut`)

- `tool` accepts `remotion` or `ffmpeg`.
- **All methods:** the server hashes the candidate file and refuses (400) when it differs from
  `produced.sha256`. The staged copy is hashed again before version commit, so a changed source
  cannot make the approved version differ from the verified candidate.
- Gate C accepts only `resource_type=videos` and a `target_ref` that is one safe filename
  component. Its managed current, staged, export, and version paths reject symlinks that would
  lead outside the project. Each staging attempt receives a unique temporary filename.
- **`COMPOSITE`:**
  - `produced.source_master_refs` must be non-empty. Each entry is
    `<shot_ref>:<selected_candidate_id>:<host_version_ref>` and must name the shot's current
    approved master in the same episode, whose current file must exist (409 otherwise).
  - `direct_dependencies` must be empty in the request. The server derives them: one
    `DependencySnapshot` per source shot, with ref `master:<shot_ref>`, version
    `<selected_candidate_id>@<host_version_ref>` and fingerprint the sha256 of the shot's
    current master file.
  - The metadata's contract type is `GoldenAComposite`.
  - A source master must have `ShotSpec` metadata; another composite cannot pose as a shot.
- After approval, the approved bytes are copied atomically to
  `output/ep<episode>-<target_ref>.mp4` and the copy is re-hashed; the response carries
  `export: {relative_path, sha256}`.
- The version record stores the staged file's `output_sha256`. An export remains eligible only
  when the approved candidate and selected version still match that record, and both the
  promoted current file and the `output/` copy hash to that stored digest.
- Each named source shot must also match its own selected version's `output_sha256`; a changed
  shot file cannot authorize a new composite or keep an existing composite current.
- The operator's `approval_record` identifies one request for its user, project, episode, and
  target. Reusing it with changed request content is a 409. A retry of the same request reuses
  the staged version and a deterministic Final Cut receipt ID. If export or receipt persistence
  fails after approval, Gate C returns 503 with `GATE_C_RETRY_SAME_APPROVAL_RECORD`; the caller
  retries the identical request instead of issuing a new approval record.

### Currency (existing mechanism)

`ApprovedMasterResolver` resolves `master:<shot_ref>` to the same snapshot shape from the
shot's current approved master. `R2ArtifactBridge.evaluate_currency` therefore marks the final
`STALE` when any shot master is re-approved or its file changes, and `BLOCKED` when a shot has
no approved master.

### Deliverables read model (`r2/m3/deliverables.py`)

`current_deliverables(project_dir)` lists every manifest entry with contract type
`GoldenAComposite` and an approved master, with:

- its currency status;
- the sha256 stored with the approved version and the sha256 of the promoted current file;
- the sha256 of its `output/` copy, if any.

A deliverable is **exportable** only when it is `CURRENT` and both the promoted current file
and the `output/` copy match the approved version's stored digest.

### Gate D (`POST /projects/{p}/gates/publish-approval`)

For `APPROVE_PUBLISH`, `deliverable_digest` must equal `sha256:<hex>` of an exportable
deliverable (409 otherwise). `REVOKE` is not checked, so an approval can always be withdrawn.

### Single-file download (download-token surface, ADR-0071)

- `POST /projects/{p}/export/deliverable/token` (session auth) returns a 300-second download
  token and only the exportable deliverables (`episode`, `target_ref`, `sha256`).
- `GET /projects/{p}/export/deliverable?download_token=…&digest=sha256:…` (token auth)
  serves a verified temporary snapshot of the `output/` copy. The snapshot is hashed before
  streaming, so a file replacement between validation and response delivery cannot change
  the downloaded bytes. Any other digest, a stale final or a mismatched copy is 404/409.
- The project ZIP already includes `output/`. The anonymous `/files` route does not serve
  `output/`.

## Limits

- `r2_m3_current/<target_ref>.mp4` is keyed by target ref, not episode (pre-existing): target
  refs must be unique within a project.
- A file another tool writes to `output/` under the same name is detected (the copy no longer
  matches) and makes the deliverable non-exportable until Gate C is re-run.
- The browser/operator workflow and the restore-derived A/B run are later V1-07 packets.

## Tests

- Integration (router, real repositories, real files): composite approval writes the export
  copy; a sha mismatch, a stale or foreign source master and caller dependencies are refused;
  Gate D accepts only an exportable digest; re-approving a shot makes the final stale and Gate
  D refuses it; the token download returns exact bytes and refuses other digests, bad tokens
  and a tampered copy; export and receipt failure retries reuse one version and receipt.
- Unit: the resolver, the read model, staged-byte verification, path guards, and download
  snapshot stability.
