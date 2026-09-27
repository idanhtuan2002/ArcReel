# R2 V1 — what "export" means (M7-D review F12)

Date: 2026-09-28. Branch `feat/r2-m7e-v1-lineage` at `c8fbeebf`. This note is
research. It sets out options and a recommendation; nothing here is decided.
License is out of scope.

## Question

V1-05 asks for "clean-target no-provider Golden review/export". V1-07 asks for
"exact gate receipts and export digests". What exactly counts as a V1 export,
and which digest proves it?

## Facts (source-backed)

1. **ADR-0089 on export.**
   - Decision 1: the operator must be able to "select a final master, export a
     playable deliverable".
   - Decision 4: "V1 stops at controlled export. Gate D authorizes the
     operator to publish the exact approved deliverable manually outside
     ArcReel."
   - Decision 5: V1 reuses existing owners. "Project, artifact, version, task
     and media state remain with their current host authorities."
   - Gate table:
     - C binds the "exact selected master/export candidate" and permits
       release packaging;
     - D binds the "exact deliverable, intended platform and visibility".
2. **The V1 strategy pipeline** (`R2_V1_PRODUCTION_RELEASE_STRATEGY.md` §2)
   runs "composition, version selection and export → C: Final Cut → D". Each
   product must keep "successful playback, export digest and post-restart
   reopen/preview evidence".
3. **Existing host export surfaces.** None of them yields one playable file
   for a whole product.
   - **Project ZIP:** `POST /projects/{name}/export/token`, then
     `GET /projects/{name}/export?scope=full|current`
     (`server/routers/projects.py:376-445`). The ZIP keeps only the top-level
     entries in `DataValidator.ALLOWED_ROOT_ENTRIES`
     (`lib/data_validator.py:156`). Anything else is reported as
     `non_standard_entry_excluded`.
   - **Jianying draft ZIP** per episode
     (`GET /projects/{name}/export/jianying-draft`). This is an editable
     draft.
   - **Presentation bundle ZIP** per unit
     (`GET /projects/{p}/presentations/{type}/{id}/bundle`), described as
     "editable-download".
   - **Raw file download:** `GET /files/{project}/{path}`
     (`server/routers/files.py:199`). It serves any file inside the project
     directory byte for byte.
4. **The host already has a slot for the final deliverable.**
   - `output/` is an allowed root entry.
   - `ProjectManager.get_output_path` exists.
   - Project status becomes `completed` when `output/*.mp4` exists
     (`lib/project_manager.py:665-670`).
   - No current code writes a final file there.
5. **Golden products today** (P1 gate surface and the restore drill).
   - Gate C (`server/routers/gates.py:133`) stages and approves one shot
     master at a time, into `r2_m3_current/`, `versions/` and the Artifact
     Manifest.
   - The composed final cut is made by the drill's own ffmpeg step and
     written to `final/<project>.mp4`. That is not an allowed root entry, so
     the file has no version record, no manifest entry and no project ZIP
     presence.
   - `production/` and `r2_m3_current/` are not allowed root entries either.
6. **Gate D does not check its digest.** `deliverable_digest` is a free
   string in the request (`gates.py:54, 203`). The server never checks it
   against a file or against a Gate C receipt.
7. **The P1 evidence** (`R2_P1_GATE_SURFACE.json`) says Gate D's digest
   "reuses whatever digest the approved Final Cut candidate already carries.
   No distinct final-export/packaging mechanism exists today."
8. **What the restore drill already proves**
   (`tests/drills/r2/golden_restore_drill.py:371-395`). On the restored
   target:
   - the stored `final/<project>.mp4` hashes to the Gate D digest, read from
     disk and not through an HTTP route;
   - re-composing from the restored masters reproduces the same bytes.
9. **Host owner of the finished video** (upstream compose-video skill,
   `agent_runtime_profile/.claude/skills/compose-video/`; upstream fix
   `99d1d036`).
   - It concatenates an episode's clips into one finished video (成片) and
     always writes it to `output/`.
   - It records no version, manifest entry or digest.
   - Scripts of other shapes use the Jianying draft export instead.
10. **M3 already registers the final as an R2 artifact**
    (`r2/m3/golden_a.py::_register_final`).
    - The key is `ArtifactKey.episode_video(ep, "FINAL-GOLDEN-A")`, with
      method `COMPOSITE`.
    - `direct_dependencies` point at each shot master's fingerprint, and
      `R2ArtifactBridge.evaluate_currency` invalidates the final when a
      shot master changes.
    - Its `approved_master` is `None`: the final is never approved.
    - Its path is `final/final.mp4`, not an allowed root entry.
11. **The Gate C route cannot accept the composed final today**
    (`server/routers/gates.py:60-75`, `r2/m3/render_plan.py:42`).
    - `FinalCutRenderedAssetRequest.tool` and `RenderedCutAsset.tool` are
      `Literal["remotion"]`.
    - `GoldenAComposer` produces a `GoldenACompositeAsset` whose `tool` is
      ffmpeg.
    - The request already carries `method` (`COMPOSITE` exists) and
      `source_master_refs`.
    - An approved Gate C candidate is committed through `VersionManager`
      into `versions/`, which is an allowed root entry. The current copy
      goes to `r2_m3_current/`, which is not.
    - `FinalCutReceipt` binds `artifact_key`, `selected_candidate_id` and
      `content_fingerprint`. `ApprovedMasterMetadata.host_version_ref`
      names the committed version file.
12. **Glossary.** CONTEXT.md, Human Gate C:
    "人对确切 selected master/export candidate 作出的最终剪辑批准" (a human's
    final-cut approval of the exact selected master/export candidate).
    _Avoid_: "render 成功、最新版本、自动 QA 分数" (a successful render, the
    latest version, an automated QA score).
13. **Deferred in P1.** P1 spec §8
    (`docs/superpowers/specs/2026-09-22-r2-p1-gate-receipt-surface-design.md`):
    "If a later, distinct export/packaging step … needs its own separate
    digest, Gate D's binding will need revisiting then".
14. **External donor: OpenMontage at pinned commit `08e2151f`** (local clone
    `content-os-r1-8/work/OpenMontage`).
    - In `pipeline_defs/animated-explainer.yaml`, the `compose` stage yields
      `render_report` and `final_review`; its output must pass ffprobe.
    - The `publish` stage has `human_approval_default: true`. Its
      `tools/publishers/export_bundle.py` byte-copies the final render to
      `video/output.mp4`, with metadata, chapters and a thumbnail.
    - Nothing is hashed, so the donor has no digest binding. R2 must be
      stricter here.



## Inferences

- **What "export" means.** In ADR-0089, "export" means that the operator
  obtains the exact playable file approved at the gates, so it can be
  published outside ArcReel. It is a byte-exact copy of the final render,
  which matches the donor model (fact 14). It is not an editable archive.
- **What Gate C should approve.** In the glossary and the ADR, Gate C is the
  approval of the *final cut*: the composed export candidate. Per-shot
  approvals in the drill are master selection, a different act.
  - A human approving a final cut must be approving the composed video.
  - The R2 COMPOSITE artifact of fact 10 is the natural object to approve.
    It already carries dependency lineage, so ADR decision 3 ("a material
    revision invalidates the affected prior approval") comes from the
    existing currency mechanism.
- **Where the export lands.** `output/` is the host's existing slot for the
  finished video (facts 4 and 9). Writing the export copy there reuses an
  owner, satisfying decision 5. It also makes the export part of the project
  ZIP and marks the project `completed`.
- **The two gaps from the first pass are real.**
  - The final has no approval owner (facts 5, 10 and 11).
  - Gate D's digest is unbound (fact 6).
  - P1 already expected the Gate D binding to be revisited (fact 13).

## Options

**O1. Keep the inference as it stands.**

- Export is any composed final whose sha256 equals the Gate D digest.
- Cost: none.
- **Rejected.** It leaves the approved object unowned and the digest unbound.
  It contradicts decision 5 and the glossary's Gate C, and V1-07 could pass
  on a file the host neither owns nor can hand out.

**O2a. Gate C approves the composed final; export is its byte-exact copy
(recommended).**

- **Final cut.** The final is composed with the existing deterministic
  `GoldenAComposer` and registered as the COMPOSITE R2 artifact (fact 10).
  Gate C approves it as the export candidate through the existing route.
  Contract change: accept the ffmpeg composite `tool` for `COMPOSITE`
  (fact 11).
- **Storage.** The approved final is committed to `versions/` like any
  master.
- **Export.** The export is a byte-exact copy of the approved final version
  in `output/`, the host's finished-video slot. The operator downloads it
  through the existing `GET /files/{project}/output/<file>` route or the
  project ZIP.
- **Export digest.** The sha256 of the bytes served by the host. It must
  equal the digest of the approved final version.
- **Gate D.** `deliverable_digest` is checked on the server against the
  current Gate C–approved final, closing the unbound-digest gap. If a shot
  master changes, currency marks the final stale, so the Gate C and Gate D
  approvals must be renewed.
- **Shot approvals.** These remain master selection, which is production
  input. They are not the Final Cut gate.

**O2b. Gate C stays per shot; Gate D binds a derived final.**

- The final is a deterministic derivative in `output/`. Gate D checks that it
  was composed from the current approved shot masters.
- **Weaker than O2a.**
  - No human Gate C approval covers the composed cut, which is the thing
    the glossary says Gate C approves.
  - Transitions, ordering and timing become unreviewed.

**O3. Export is the existing packaging surfaces.**

- The project ZIP, the Jianying draft or the presentation bundle.
- **Rejected as the deliverable.** These are editable or archive formats,
  not the playable deliverable of decision 1.
- **Kept as secondary surfaces.** Under O2a the project ZIP includes
  `output/` and so carries the export too.

## Recommendation

**O2a**, recorded as a follow-up decision to ADR-0090, so that V1-07
implements it and does not redefine it.

**V1-05.** V1-05 closes on current evidence under O2a, with this limit
disclosed. The drill proves three things:

1. the Gate D–approved bytes survive restore byte-exact;
2. they are reproducible from the restored masters;
3. the backup captures and restores every file that export reads.

The drill does not prove that the final is host-owned, Gate C–approved or
downloadable. Those are product gaps, not recovery gaps.

**V1-07** (repair observed product gaps). Its first packet is:

1. accept the COMPOSITE final at Gate C;
2. write the export copy to `output/`;
3. check the Gate D digest on the server;
4. test the download through the host route on a restore-derived target.

**Why V1-05 need not wait.** V1-05's purpose is recovery diagnosability.
Every file O2a's export reads (versions, manifest, masters) is already
proven restored and verified. So implementing O2a does not change V1-05's
recovery claim.
