# M8-C frame custody seam: M7 reuse limits

Status: source-backed design research at `00190a19fac1e13b9e1787e87ef1989dd32dec5f`, not frame implementation or M8-C acceptance.

## Verified source behavior

The live Gate C HTTP fixture now proves two different episode-video keys can have independently versioned approved heads (`tests/integration/server/routers/test_gates_master_authority.py::test_two_gate_c_video_masters_have_distinct_current_heads`). It does not prove anything about extracted frames or pair suitability.

`DatabaseMasterResolver.get_exact` accepts a database head when the legacy projection returns `None` (`r2/host_hardening/master_resolver.py:37-58`; the behavior is explicitly covered by `tests/unit/r2/host_hardening/test_master_resolver.py:64-71`). An unfinished Gate C promotion can have exactly that state. `verify_project_masters` rejects it by comparing the database and projected key sets (`r2/host_hardening/master_authority.py:217-245`), and `server.services.master_authority.verify_masters` provides a scoped server entrypoint. Frame registration must therefore require the scoped **complete projection check**, not rely on `DatabaseMasterResolver.get_exact` alone.

`lib.candidate_store.prepare_candidate` checks whether `final_path` exists before writing its temporary file, then calls `os.replace(tmp_path, final_path)` (`lib/candidate_store.py:79-88,155-171`). `os.replace` overwrites a destination created by another writer after the first check. A bounded fault-injection probe patched the `os.replace` call to create competing bytes at the destination immediately before the real call; the call returned successfully and the competing bytes were replaced (`competing_destination_overwritten= True`). Existing duplicate tests cover a destination already present before the check (`tests/unit/lib/test_candidate_store.py:195-212`), not this interleaving. This is a storage seam issue for the proposed frame path; the probe does not establish that a production race has occurred.

The probe ran with the V2 worktree Python environment and `PYTHONPATH=.` from the design worktree. Its essential interleaving was:

```python
real_replace = candidate_store.os.replace

def competitor_before_replace(src, dst):
    Path(dst).write_bytes(b"frame-from-writer-b")
    return real_replace(src, dst)

with patch.object(candidate_store.os, "replace", side_effect=competitor_before_replace):
    candidate_store.prepare_candidate(
        identity=frame_a_identity,
        source_file=frame_a_source,
        final_path=target,
        media_root=media_root,
        media_probe=probe,
    )
assert target.read_bytes() == b"frame-from-writer-a"
```

`frame_a_identity.expected_content_digest` was the SHA-256 of `b"frame-from-writer-a"`; `target` did not exist before the call. This probe forces only the file-publication interleaving, not a real multi-process schedule or database commit.

The candidate-object row has an immutable candidate ID, object path, byte size, content digest and media-probe digest, but no parent/recipe lineage (`lib/db/models/host_hardening.py:293-320`). The proposed `SpatialFrameDerivationReceipt` remains necessary. The current repository insertion has scoped uniqueness and rejects conflicting candidate IDs (`lib/db/repositories/host_hardening.py:804-861`), but database uniqueness cannot undo an overwritten file.

## Design consequence

Frame derivation needs a publish-if-absent file operation that cannot overwrite a concurrent destination, including one created between validation and publish. An exact equal-byte replay may reuse the object only after rehashing the existing file and matching its registered receipt; unequal bytes must fail without changing either file. The frame service must use project-confined paths and revalidate path containment at the publication boundary. The frame receipt and candidate row must commit together, with exact command replay and conflict checks. A crash after file publication but before database commit leaves an unregistered object, which ordinary readers refuse; retry may register it only after rechecking its bytes, recipe, parent and command.

Resolve the parent head with a scoped `verify_masters` check and exact candidate-object verification. Decode can happen outside a database lock, but before receipt commit the service must lock the relevant master authority row, repeat the scoped projection/head check, compare it with the pinned parent, and rehash both parent and frame bytes. Promotion and live consumption must repeat the same currentness and receipt checks. A replaced parent invalidates new use of its derived frame; historical evidence remains immutable.

Required adversarial fixture: create two Gate C approved video parents; derive and register both frames with exact receipts; admit one suitable pair and reject one unsuitable pair. Also force a competing destination just before publication, a missing projection, a superseded parent between decode and commit, an altered frame, wrong project, unsupported timestamp and decoder-version mismatch. The current two-master fixture covers only the first clause.

The existing unit files `tests/unit/lib/test_candidate_store.py` and `tests/unit/r2/host_hardening/test_master_resolver.py` passed **17 tests** together under the isolated SQLite test URL. Those tests confirm the current behavior described above; they do not exercise the required frame service or resolve the publication race.
