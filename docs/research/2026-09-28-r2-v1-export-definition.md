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
9. **External reference.** OpenMontage and Remotion, the vendored render
   donor, treat the rendered output file as the deliverable. There is no
   separate packaging step.

## Inferences

- In ADR-0089, "export" means that the operator obtains the exact playable
  file that Gate D approved, so it can be published outside ArcReel. That is
  a byte-exact file handed out under the host's authority, not an editable
  archive.
- **Owner gap.** The composed final is the object Gate D approves, but no
  host authority owns it today. Decision 5 says it belongs to an existing
  owner.
- **Binding gap.** Gate D's digest is not bound to anything.
- **Why the ZIP falls short.** The existing project ZIP is a project archive
  and backup-style export. Today it would leave out the Golden final and
  masters (fact 5).

## Options

**O1. Keep the inference as it stands.**

- **Definition:** export is any composed final whose sha256 equals the Gate D
  `deliverable_digest`.
- **Cost:** none.
- **Weakness:** it leaves the owner and binding gaps unnamed. V1-07 could
  pass on a file that the host neither owns nor can hand out.

**O2. Export is the host-owned final, handed out byte-exact (recommended).**

- **Definition:** a V1 export is the composed final deliverable stored under
  host authority. The natural slot is `output/`, which the host already
  reserves (fact 4).
  - Gate C binds that exact file.
  - Gate D's `deliverable_digest` equals the digest bound by Gate C.
  - The operator gets it through an existing host download route
    (`GET /files/{project}/output/<file>`), byte-identical.
- **Export digest:** the sha256 of the bytes served by the host, which must
  equal the Gate D digest.
- **V1-05:** closes on the evidence already gathered.
  - The drill proves the approved final survives restore byte-exact and is
    reproducible from the restored masters.
  - It proves this for an unowned file path, and says so as a limit.
- **V1-07:** carries the product gaps, as "observed product gaps" (per the
  backlog):
  1. compose the final into host ownership;
  2. bind Gate C and Gate D to it;
  3. download it through the host route.
- **Why it fits:** it matches ADR-0089 decisions 1, 4 and 5, reuses existing
  surfaces, and adds no new export mechanism.

**O3. Export is the existing packaging surfaces.**

- **Definition:** export is the project ZIP (`scope=current`), the Jianying
  draft or the presentation bundle.
- **Weakness:** these are editable or archive formats, not the "playable
  deliverable" of ADR-0089 decision 1. The ZIP currently leaves out the R2
  directories.
- **Role:** useful as secondary evidence, but they cannot carry the Gate D
  digest.

## Unknowns

- **How the final should be composed.** A host composition step could reuse
  `r2/m3/composition.py`. Alternatively, the M3 host integration could stage
  the final as its own artifact. This is a V1-07 design choice.
- **Which gate binds the final.** Should Gate C bind the whole final as one
  artifact (per ADR "exact selected master/export candidate") or only the
  shot masters, with the final derived from them? The receipts suggest the
  final should be bound, but this needs a V1-07 design check.

## Recommendation

O2. Record it as a follow-up decision, in ADR-0090's follow-up section or as
a backlog note, so V1-07 does not redefine it.

- **V1-05:** accepted under O2, with the unowned-path limit disclosed.
- **V1-07:** owns the three gaps: host-owned final, Gate C/D binding, and
  download through the host route.
