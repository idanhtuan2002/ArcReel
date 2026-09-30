"""M8-B Creative Canvas accessibility in a real browser: axe-core and keyboard paths.

Uses the benchmark harness (production build, mocked API, seeded graph) and injects
axe-core 4.13.0 from frontend/node_modules.

    (cd frontend && pnpm build) && uv run playwright install chromium
    uv run python -m pytest tests/e2e/test_m8b_canvas_a11y.py
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.test_m8b_canvas_benchmark import FRONTEND, FakeApi, chromium, episode_graph, open_canvas, preview_server

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

AXE = FRONTEND / "node_modules" / "axe-core" / "axe.min.js"
WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]


@pytest.fixture(scope="module")
def preview_url() -> Iterator[str]:
    with preview_server() as url:
        yield url


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with chromium() as launched:
        yield launched


@pytest.fixture
def canvas(browser: Browser, preview_url: str) -> Iterator[Page]:
    page = open_canvas(browser, preview_url, FakeApi(episode_graph(25, 37)))
    page.evaluate("document.activeElement instanceof HTMLElement && document.activeElement.blur()")
    page.keyboard.press("2")  # zoom 1.0: full node detail
    page.wait_for_timeout(300)
    try:
        yield page
    finally:
        page.context.close()


def _axe(page: Page) -> list[dict[str, Any]]:
    """axe violations inside the Canvas page (header, board and filmstrip), WCAG 2.1 A and AA."""
    page.add_script_tag(path=str(AXE))
    version = page.evaluate("window.axe.version")
    assert version == "4.13.0"
    result = page.evaluate(
        """async (tags) => {
            const root = document.querySelector('h1').closest('div.flex.h-full');
            const out = await window.axe.run(root, { runOnly: { type: 'tag', values: tags } });
            return out.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.map((n) => n.target) }));
        }""",
        WCAG_TAGS,
    )
    return list(result)


def test_the_canvas_has_no_axe_violations(canvas: Page) -> None:
    violations = _axe(canvas)

    assert violations == [], json.dumps(violations, indent=2)


def test_the_conflict_state_has_no_axe_violations(canvas: Page) -> None:
    canvas.route(
        "**/api/v1/projects/bench/m8/exploration/revisions",
        lambda route: route.fulfill(status=409, content_type="application/json", body='{"detail":"moved"}'),
    )
    canvas.route(
        "**/api/v1/projects/bench/m8/exploration/candidates/canvas-episode-1",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"candidate_id":"canvas-episode-1","current_revision":7,"head_version":7}',
        ),
    )
    canvas.get_by_role("button", name="Add note").click()
    canvas.keyboard.press("Control+s")

    alert = canvas.get_by_role("alert")
    alert.wait_for()
    assert "changed in another tab or device" in alert.inner_text()
    assert _axe(canvas) == []


def test_nodes_are_reachable_and_removable_from_the_keyboard(canvas: Page) -> None:
    first = canvas.locator(".react-flow__node").first
    first.focus()
    node_id = first.get_attribute("data-id")
    assert first.get_attribute("aria-describedby")
    assert canvas.evaluate("document.activeElement.classList.contains('react-flow__node')")

    canvas.keyboard.press("Enter")
    canvas.keyboard.press("Delete")

    canvas.wait_for_function(f"!document.querySelector('.react-flow__node[data-id=\"{node_id}\"]')")


def test_arrow_keys_move_a_selected_node_and_undo_restores_it(canvas: Page) -> None:
    node = canvas.locator(".react-flow__node-beat").first
    node.focus()
    canvas.keyboard.press("Enter")
    before = node.bounding_box()
    assert before is not None

    canvas.keyboard.press("ArrowRight")
    canvas.wait_for_timeout(100)
    moved = node.bounding_box()
    assert moved is not None
    assert moved["x"] > before["x"]

    canvas.evaluate("document.activeElement instanceof HTMLElement && document.activeElement.blur()")
    canvas.keyboard.press("Control+z")
    canvas.wait_for_timeout(100)
    restored = node.bounding_box()
    assert restored is not None
    assert abs(restored["x"] - before["x"]) < 1


def test_the_filmstrip_reorders_shots_from_the_keyboard(canvas: Page) -> None:
    listbox = canvas.get_by_role("listbox", name="Storyboard order")
    options = listbox.get_by_role("option")
    first_label = options.nth(0).get_attribute("aria-label") or ""
    second_label = options.nth(1).get_attribute("aria-label") or ""
    options.nth(0).focus()

    canvas.keyboard.press("Alt+ArrowRight")

    canvas.wait_for_function(
        "(name) => document.querySelectorAll('[role=option]')[1].getAttribute('aria-label').endsWith(name)",
        arg=first_label.split(": ", 1)[1],
    )
    assert (options.nth(0).get_attribute("aria-label") or "").endswith(second_label.split(": ", 1)[1])
    assert canvas.get_by_text("moved to position 2.").count() == 1


def test_enter_on_a_shot_focuses_its_storyboard_on_the_canvas(canvas: Page) -> None:
    options = canvas.get_by_role("listbox", name="Storyboard order").get_by_role("option")
    options.nth(0).focus()

    canvas.keyboard.press("Enter")

    canvas.wait_for_function("document.activeElement.classList.contains('react-flow__node-group')")
    assert canvas.evaluate("document.activeElement.classList.contains('selected')")


def test_text_fields_have_names_and_commit_on_blur(canvas: Page) -> None:
    node = canvas.locator(".react-flow__node-beat").first
    title = node.get_by_role("textbox", name="Title")
    text = node.get_by_role("textbox", name="Text")
    assert title.count() == 1
    assert text.count() == 1

    title.fill("Opening hook")
    canvas.keyboard.press("Tab")

    assert text.evaluate("(el) => el === document.activeElement")
    assert title.input_value() == "Opening hook"
