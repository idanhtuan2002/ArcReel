# M8-C Take target version probe

Evidence point: design worktree `e07a6476d46a63cd87cac69a12c51ce08ec12c01`.
This is an adapter-level synthetic probe, not a target-registry or screenplay-admission integration test.

`TakeDirectorAdapter` derives one scene and shot per admitted screenplay scene. Its
`_scene_spec` and `_shot_spec` functions set the body `version` to `1` and reuse
the source scene ID (the shot ID adds `-TAKE-1`). `ApprovedScreenplayReader`
uses its own unit of work to check the current admission head, so the adapter
cannot supply a lock held through a later target-registration write.

I executed the checked-in `test_take_director.py` fixture helpers with two
synthetic screenplay versions (`2` and `3`) for `scene-1`. The second scene
changes `purpose`; its synthetic content hash also changes. The fake reader
returns each matching screenplay to the real adapter. Canonical body digests
were computed with `r2.advanced_creative.digests.digest_canonical`:

Run from the design worktree with the repository Python environment:

```python
import asyncio
import runpy
from r2.advanced_creative.digests import digest_canonical
from r2.production_intelligence.take_director import TakeDirectorAdapter

fixture = runpy.run_path("tests/unit/r2/production_intelligence/test_take_director.py")
scene = fixture["_scene"]("scene-1")
first = fixture["_screenplay"](version=2, scenes=[scene])
second = fixture["_screenplay"](
    version=3, scenes=[scene.model_copy(update={"purpose": "show the changed location stakes"})]
).model_copy(update={"content_hash": "sha256:" + "d9" * 32})

async def derive(screenplay):
    adapter = TakeDirectorAdapter(fixture["_FakeReader"](screenplay), user_id="u1", project_name="project-a")
    return await adapter.direct(fixture["_admitted_ref"](screenplay))

for screenplay in (first, second):
    result = asyncio.run(derive(screenplay))
    for target in (*result.scenes, *result.shots):
        print(target.id, target.version, digest_canonical(target.model_dump(mode="json")))
```

| Derived target | First ID / body version / digest | Second ID / body version / digest |
| --- | --- | --- |
| Scene | `scene-1` / `1` / `sha256:b6f782853399e8be2728ef854ae663da31809bffd7fd5b6c6efad7506765a813` | `scene-1` / `1` / `sha256:d80debc661b5efc3b841231262fa5857d75140567ef11e5323a1c824005157d4` |
| Shot | `scene-1-TAKE-1` / `1` / `sha256:c8fd119bbba14ad3ac28c33037224d52ce09f65dd25a7cda7fffc1a45a5229b5` | `scene-1-TAKE-1` / `1` / `sha256:b63b8708c825d3017588f6895023a035874b8107d4e7d2da13709c78c8f43efa` |

This confirms the adapter body `version` cannot be a durable target version:
the same ID and body version can have different content across screenplay
admissions. ADR-0102's separate monotonic registry version addresses that
collision. The probe does **not** prove registration replay, locking, or
current-admission correctness. Those require two real admitted screenplay
versions, a same-session registration writer, and PostgreSQL concurrency tests.
