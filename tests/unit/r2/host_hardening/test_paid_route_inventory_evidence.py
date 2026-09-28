"""The committed paid-route inventory evidence matches the source-derived inventory."""

from __future__ import annotations

import json
from pathlib import Path

from r2.host_hardening.paid_routes import paid_route_inventory
from r2.host_hardening.route_inventory import BUILTIN_VIDEO_SUBMIT_PROVIDER, PAID_ASYNC_SUBMIT_FAMILIES
from r2.host_hardening.route_qualifications import UNQUALIFIABLE_ROUTE_KINDS, adapter_version_for

EVIDENCE = Path(__file__).resolve().parents[4] / "docs/r2/evidence/R2_V1X_PAID_ROUTE_INVENTORY_2026-09-29.json"


def _evidence() -> dict[str, object]:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_every_source_route_is_recorded_with_its_adapter_version_and_nothing_else() -> None:
    recorded = {row["route_ref"]: row for row in _evidence()["routes"]}  # type: ignore[union-attr]

    source = {route.ref: route for route in paid_route_inventory()}

    assert set(recorded) == set(source)
    for ref, route in source.items():
        row = recorded[ref]
        assert (row["kind"], row["provider_id"], row["media_type"]) == (route.kind, route.provider_id, route.media_type)
        assert row["adapter_version"] == adapter_version_for(route)
        disposition = str(row["release_disposition"])
        if route.kind in UNQUALIFIABLE_ROUTE_KINDS:
            assert disposition.startswith("REFUSED_IN_RELEASE")
        elif route.kind == "agent":
            assert disposition.startswith("REFUSED_UNTIL_QUALIFIED")
            assert "ADR-0093" in disposition
        elif route.media_type == "video":
            assert disposition.startswith("DISABLED_IN_RELEASE")
        else:
            assert disposition.startswith("REFUSED_UNTIL_QUALIFIED")


def test_the_recorded_async_video_submit_families_match_the_frozen_inventory() -> None:
    evidence = _evidence()

    recorded = [
        (row["provider_id"], row["endpoint_id"], row["adapter_version"], row["profile_ref"])
        for row in evidence["async_video_submit_families"]  # type: ignore[union-attr]
    ]

    assert recorded == [
        (f.key.provider_id, f.key.endpoint_id, f.key.adapter_version, f.capability_profile_ref)
        for f in PAID_ASYNC_SUBMIT_FAMILIES
    ]
    assert evidence["builtin_video_submit_provider"] == BUILTIN_VIDEO_SUBMIT_PROVIDER
