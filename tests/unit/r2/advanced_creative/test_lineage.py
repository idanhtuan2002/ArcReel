"""Version 1 of the server-resolved M8 lineage (ADR-0098)."""

from __future__ import annotations

import hashlib

from r2.advanced_creative.digests import digest_canonical
from r2.advanced_creative.lineage import resolve_episode_lineage


def test_the_content_basis_binds_the_episode_and_its_script_bytes() -> None:
    lineage = resolve_episode_lineage("demo", 2, b'{"a":1}')

    assert lineage.content_basis_digest == digest_canonical(
        {
            "basis_kind": "host_episode_script",
            "episode": 2,
            "script_digest": "sha256:" + hashlib.sha256(b'{"a":1}').hexdigest(),
        }
    )
    assert resolve_episode_lineage("demo", 3, b'{"a":1}').content_basis_digest != lineage.content_basis_digest
    assert resolve_episode_lineage("demo", 2, b'{"a":2}').content_basis_digest != lineage.content_basis_digest


def test_every_episode_binds_the_host_profile_and_no_master() -> None:
    lineage = resolve_episode_lineage("demo", 1, b"")

    assert lineage.project_name == "demo"
    assert (lineage.creative_profile_id, lineage.creative_profile_version) == ("arcreel.host", "1")
    assert lineage.policy_digest == digest_canonical(
        {"profile_id": "arcreel.host", "profile_version": "1", "rules": []}
    )
    assert lineage.approved_master_id is None
    assert lineage.approved_master_digest is None
