from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import cast

import pytest

from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.recovery_config import RecoveryConfigInvalid, parse_recovery_config_v1


def valid_mapping() -> dict[str, object]:
    def digest(char: str) -> str:
        return "sha256:" + char * 64

    return {
        "schema_version": 1,
        "backup_mechanism": "logical_pg_dump_v1",
        "source_deployment_id": "deployment-1",
        "release_git_sha": "a" * 40,
        "release_image_digest": digest("b"),
        "postgres_server_image_digest": digest("c"),
        "pg_dump": {"version": "pg_dump (PostgreSQL) 18.0", "binary_digest": digest("d")},
        "pg_restore": {"version": "pg_restore (PostgreSQL) 18.0", "binary_digest": digest("e")},
        "ffprobe": {"version": "ffprobe version 8.0", "binary_digest": digest("f")},
        "ffmpeg": {"version": "ffmpeg version 8.0", "binary_digest": digest("0")},
        "db_root_id": "db-1",
        "project_root_id": "projects-1",
        "media_root_id": "media-1",
        "service_inventory": [
            {
                "service_id": "svc-app",
                "kind": "app",
                "image_digest": digest("1"),
                "can_write": True,
                "instance_ids": ["app-1"],
            },
            {
                "service_id": "svc-gc",
                "kind": "gc_cleanup",
                "image_digest": digest("2"),
                "can_write": True,
                "instance_ids": ["gc-1"],
            },
            {
                "service_id": "svc-pg",
                "kind": "postgres",
                "image_digest": digest("3"),
                "can_write": True,
                "instance_ids": ["postgres-1"],
            },
            {
                "service_id": "svc-scan",
                "kind": "recovery_scanner",
                "image_digest": digest("4"),
                "can_write": True,
                "instance_ids": ["scan-1"],
            },
            {
                "service_id": "svc-worker",
                "kind": "worker",
                "image_digest": digest("5"),
                "can_write": True,
                "instance_ids": ["worker-1"],
            },
        ],
        "writer_inventory_digest": "sha256:b57fb25e3a2aa2b588f820b8e34a81366cfeda8c58eb4d2bcfad6dac282927e4",
        "effective_compose_digest": digest("6"),
        "network_egress_policy_digest": digest("7"),
        "provider_route_policy_digest": digest("8"),
        "paid_routes_enabled": False,
        "capability_registry_digest": digest("9"),
        "agent_runtime_profile_digest": digest("a"),
    }


def services(data: dict[str, object]) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", data["service_inventory"])


def test_valid_configuration_hashes_exact_canonical_record() -> None:
    raw = canonical_json_bytes(valid_mapping())
    record, fingerprint = parse_recovery_config_v1(raw)
    assert record.source_deployment_id == "deployment-1"
    assert fingerprint == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert not hasattr(record, "approved")


def test_release_identity_changes_full_configuration_fingerprint() -> None:
    first = valid_mapping()
    second = deepcopy(first)
    second["release_image_digest"] = "sha256:" + "e" * 64
    _, first_digest = parse_recovery_config_v1(canonical_json_bytes(first))
    _, second_digest = parse_recovery_config_v1(canonical_json_bytes(second))
    assert first_digest != second_digest


def test_postgres_image_changes_full_configuration_fingerprint() -> None:
    first = valid_mapping()
    second = deepcopy(first)
    services(second)[2]["image_digest"] = "sha256:" + "e" * 64
    _, first_digest = parse_recovery_config_v1(canonical_json_bytes(first))
    _, second_digest = parse_recovery_config_v1(canonical_json_bytes(second))
    assert first_digest != second_digest


@pytest.mark.parametrize("version", [2, True, 1.0, "1"])
def test_schema_version_requires_exact_json_integer_one(version: object) -> None:
    data = valid_mapping()
    data["schema_version"] = version
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


@pytest.mark.parametrize("mechanism", ["physical_pitr_v1", "logical_pg_dump_v2", None])
def test_only_explicit_logical_dump_v1_profile_is_admitted(mechanism: object) -> None:
    data = valid_mapping()
    data["backup_mechanism"] = mechanism
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


def test_paid_routes_cannot_be_enabled_by_this_v1_profile() -> None:
    data = valid_mapping()
    data["paid_routes_enabled"] = True
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


def test_malformed_release_digest_rejects() -> None:
    data = valid_mapping()
    data["release_image_digest"] = "sha256:ABC"
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


@pytest.mark.parametrize("git_sha", ["A" * 40, "a" * 40 + "\n", "a" * 39, "a" * 41])
def test_release_git_sha_must_be_exact_lowercase_hex(git_sha: str) -> None:
    data = valid_mapping()
    data["release_git_sha"] = git_sha
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


@pytest.mark.parametrize("field", ["schema_version", "source_deployment_id", "pg_dump", "service_inventory"])
def test_missing_required_field_rejects(field: str) -> None:
    data = valid_mapping()
    del data[field]
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "postgres://secret"),
        ("source_deployment_id", "/absolute/path"),
        ("media_root_id", "s3://bucket"),
    ],
)
def test_unknown_or_nonlogical_identity_rejects(field: str, value: str) -> None:
    data = valid_mapping()
    data[field] = value
    with pytest.raises(RecoveryConfigInvalid) as caught:
        parse_recovery_config_v1(canonical_json_bytes(data))
    assert "secret" not in str(caught.value)


def test_nested_secret_field_rejects_without_echoing_value() -> None:
    data = valid_mapping()
    tool = cast("dict[str, object]", data["pg_dump"])
    tool["password"] = "do-not-echo-secret"
    with pytest.raises(RecoveryConfigInvalid) as caught:
        parse_recovery_config_v1(canonical_json_bytes(data))
    assert "do-not-echo-secret" not in str(caught.value)


def test_rejected_secret_is_absent_from_exception_context_chain() -> None:
    data = valid_mapping()
    tool = cast("dict[str, object]", data["pg_dump"])
    tool["password"] = "do-not-echo-secret"
    with pytest.raises(RecoveryConfigInvalid) as caught:
        parse_recovery_config_v1(canonical_json_bytes(data))
    pending: list[BaseException] = [caught.value]
    seen: set[int] = set()
    while pending:
        error = pending.pop()
        if id(error) in seen:
            continue
        seen.add(id(error))
        assert "do-not-echo-secret" not in str(error)
        if error.__cause__ is not None:
            pending.append(error.__cause__)
        if error.__context__ is not None:
            pending.append(error.__context__)


def test_noncanonical_whitespace_and_duplicate_keys_reject() -> None:
    raw = canonical_json_bytes(valid_mapping())
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(raw + b" ")
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(raw.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'))


@pytest.mark.parametrize("root", ["db_root_id", "project_root_id"])
def test_root_aliasing_rejects(root: str) -> None:
    data = valid_mapping()
    data[root] = data["media_root_id"]
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


def test_unsorted_service_inventory_rejects() -> None:
    data = valid_mapping()
    services(data).reverse()
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


def test_duplicate_service_id_rejects() -> None:
    data = valid_mapping()
    services(data)[1]["service_id"] = services(data)[0]["service_id"]
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


@pytest.mark.parametrize("instances", [[], ["worker-2", "worker-1"], ["worker-1", "worker-1"]])
def test_service_instance_ids_must_be_nonempty_sorted_unique(instances: list[str]) -> None:
    data = valid_mapping()
    services(data)[4]["instance_ids"] = instances
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


def test_duplicate_kind_instance_pair_rejects() -> None:
    data = valid_mapping()
    services(data).append(
        {
            "service_id": "svc-worker-two",
            "kind": "worker",
            "image_digest": "sha256:" + "a" * 64,
            "can_write": True,
            "instance_ids": ["worker-1"],
        }
    )
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


@pytest.mark.parametrize("kind", ["postgres", "app", "worker", "recovery_scanner", "gc_cleanup"])
def test_required_service_kind_cannot_be_missing(kind: str) -> None:
    data = valid_mapping()
    services(data)[:] = [service for service in services(data) if service["kind"] != kind]
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


def test_writer_digest_must_match_exact_service_inventory() -> None:
    data = valid_mapping()
    data["writer_inventory_digest"] = "sha256:" + "a" * 64
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


@pytest.mark.parametrize("kind", ["postgres", "app", "worker", "recovery_scanner", "gc_cleanup"])
def test_required_writer_cannot_claim_read_only(kind: str) -> None:
    data = valid_mapping()
    next(service for service in services(data) if service["kind"] == kind)["can_write"] = False
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


def test_other_service_cannot_hide_a_writer() -> None:
    data = valid_mapping()
    services(data).insert(
        2,
        {
            "service_id": "svc-other",
            "kind": "other",
            "image_digest": "sha256:" + "a" * 64,
            "can_write": True,
            "instance_ids": ["other-1"],
        },
    )
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


def test_additional_writer_instance_requires_and_accepts_updated_fence_digest() -> None:
    data = valid_mapping()
    services(data)[4]["instance_ids"] = ["worker-1", "worker-2"]
    writer_payload = b'[["app","app-1"],["gc_cleanup","gc-1"],["recovery_scanner","scan-1"],["worker","worker-1"],["worker","worker-2"]]'
    data["writer_inventory_digest"] = "sha256:" + hashlib.sha256(writer_payload).hexdigest()
    record, _ = parse_recovery_config_v1(canonical_json_bytes(data))
    assert record.service_inventory[4].instance_ids == ("worker-1", "worker-2")


def test_read_only_other_service_is_allowed_and_bound_by_fingerprint() -> None:
    data = valid_mapping()
    services(data).insert(
        2,
        {
            "service_id": "svc-other",
            "kind": "other",
            "image_digest": "sha256:" + "a" * 64,
            "can_write": False,
            "instance_ids": ["other-1"],
        },
    )
    _, first_digest = parse_recovery_config_v1(canonical_json_bytes(data))
    services(data)[2]["image_digest"] = "sha256:" + "b" * 64
    _, second_digest = parse_recovery_config_v1(canonical_json_bytes(data))
    assert first_digest != second_digest


@pytest.mark.parametrize("flag", [0, 1, "false", None])
def test_paid_routes_flag_must_be_json_boolean(flag: object) -> None:
    data = valid_mapping()
    data["paid_routes_enabled"] = flag
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))


@pytest.mark.parametrize("version", ["", " pg_dump 18", "pg_dump 18 ", "pg_dump\n18", "x" * 257])
def test_tool_version_is_bounded_printable_exact_text(version: str) -> None:
    data = valid_mapping()
    tool = cast("dict[str, object]", data["pg_dump"])
    tool["version"] = version
    with pytest.raises(RecoveryConfigInvalid):
        parse_recovery_config_v1(canonical_json_bytes(data))
