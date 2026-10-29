"""Same-fixture qualification of the embedded host-v1 probe catalog on the qualified host."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from r2.quality.errors import ProbeFailedError
from r2.quality.host_catalog import CONTAINER_CONFIG, DECODE_CONFIG, HOST_CATALOG, WORKER_PARSER_DIGEST
from server.services import quality_probe_worker
from tests.integration.server.services.test_quality_probe_recipes import config_for, measure
from tests.integration.server.services.test_quality_probe_recipes import project as project
from tests.integration.server.services.test_quality_probe_runtime import tool


def test_the_catalog_pins_this_hosts_tools_and_the_current_probe_worker() -> None:
    for config in HOST_CATALOG.configs:
        for pinned in config.tools:
            assert pinned.model_dump(mode="json") == tool(pinned.name) | {"model_digest": None}
    worker = Path(quality_probe_worker.__file__).read_bytes()
    assert "sha256:" + hashlib.sha256(worker).hexdigest() == WORKER_PARSER_DIGEST


def test_each_rule_has_its_own_config() -> None:
    assert [(c.rule_id, c.recipe) for c in HOST_CATALOG.configs] == [
        ("probe-container", "CONTAINER_STREAM"),
        ("probe-decode", "DECODE"),
    ]


_IDENTITY = {"config_id", "rule_id", "parser_digest"}


@pytest.mark.parametrize(("config", "recipe"), [(CONTAINER_CONFIG, "CONTAINER_STREAM"), (DECODE_CONFIG, "DECODE")])
def test_the_catalog_bodies_are_the_a4_qualified_bodies(config, recipe: str) -> None:
    assert config.model_dump(mode="json", exclude=_IDENTITY) == config_for(recipe).model_dump(
        mode="json", exclude=_IDENTITY
    )


def _measured(config):
    """The catalog body under the rule id the A4 request fixture binds; measurement never reads identity fields."""
    return config.model_copy(update={"rule_id": "probe"})


@pytest.mark.parametrize("media", ["av.mp4", "av_fullrange.mp4", "video_only.mp4"])
async def test_the_catalog_configs_measure_the_recipe_fixtures(project: Path, media: str) -> None:
    container = await measure(project, _measured(CONTAINER_CONFIG), media)
    assert container.measurement.status == "PASS"
    decoded = await measure(project, _measured(DECODE_CONFIG), media)
    assert decoded.measurement.status == "PASS"


@pytest.mark.parametrize("media", ["truncated.mp4", "mpeg4.mp4"])
async def test_the_catalog_configs_refuse_unqualified_media(project: Path, media: str) -> None:
    with pytest.raises(ProbeFailedError):
        await measure(project, _measured(CONTAINER_CONFIG), media)
