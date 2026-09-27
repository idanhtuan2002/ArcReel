from __future__ import annotations

import pytest

from lib.budget_reservation import BudgetReservationIntegrityError
from scripts.r2 import budget_scope


async def _run(argv: list[str]) -> dict[str, str]:
    # 与测试同一事件循环驱动命令体：main() 自带 asyncio.run，另起循环会让 asyncpg 连接跨循环。
    return await budget_scope._run(budget_scope.build_parser().parse_args(argv))


async def test_create_then_show_reports_the_remaining_authorization(db_factory, monkeypatch) -> None:
    monkeypatch.setattr(budget_scope, "async_session_factory", db_factory)
    monkeypatch.setenv("ARCREEL_BUDGET_SCOPE", "release")

    created = await _run(["create", "--currency", "usd", "--limit", "50"])
    assert created["scope"] == "release:USD"

    shown = await _run(["show", "--currency", "USD"])
    assert (shown["currency"], shown["remaining"]) == ("USD", "50.000000")


async def test_an_unknown_or_duplicate_scope_is_refused(db_factory, monkeypatch) -> None:
    monkeypatch.setattr(budget_scope, "async_session_factory", db_factory)

    with pytest.raises(BudgetReservationIntegrityError, match="unknown budget scope"):
        await _run(["show", "--currency", "CNY"])

    await _run(["create", "--currency", "CNY", "--limit", "10"])
    with pytest.raises(BudgetReservationIntegrityError, match="already exists"):
        await _run(["create", "--currency", "CNY", "--limit", "10"])


def test_a_negative_limit_is_rejected_by_the_parser() -> None:
    with pytest.raises(SystemExit):
        budget_scope.build_parser().parse_args(["create", "--currency", "USD", "--limit", "-1"])
