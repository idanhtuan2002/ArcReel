"""Operator CLI for release-deployment budget scopes (ADR-0091).

A release deployment (``ARCREEL_RELEASE_MODE=PRODUCTION_CANDIDATE``) refuses every
paid call unless a budget scope exists for the call's currency and has room for
the call's reservation. Scopes are named ``<prefix>:<currency>``, with the prefix
from ``ARCREEL_BUDGET_SCOPE`` (default ``release``). A scope's limit is fixed at
creation; to authorize more, create a scope under a new prefix and point
``ARCREEL_BUDGET_SCOPE`` at it.

    create --currency USD --limit 50     authorize 50 USD
    show --currency USD                  limit, reserved, committed and remaining
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from lib.budget_guard import budget_scope_ref
from lib.budget_reservation import BudgetReservationIntegrityError
from lib.db import async_session_factory
from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository


def _money(raw: str) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"not a decimal amount: {raw!r}") from exc
    if not value.is_finite() or value < 0:
        raise argparse.ArgumentTypeError(f"amount must be a finite non-negative decimal: {raw!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--currency", required=True)
    create.add_argument("--limit", required=True, type=_money)
    show = sub.add_parser("show")
    show.add_argument("--currency", required=True)
    return parser


def _snapshot_json(snapshot) -> dict[str, str]:
    remaining = snapshot.authorized_limit - snapshot.reserved_total - snapshot.committed_total
    return {
        "scope": snapshot.budget_scope_ref,
        "currency": snapshot.currency,
        "authorized_limit": str(snapshot.authorized_limit),
        "reserved_total": str(snapshot.reserved_total),
        "committed_total": str(snapshot.committed_total),
        "remaining": str(remaining),
    }


async def _run(args: argparse.Namespace) -> dict[str, str]:
    currency = args.currency.strip().upper()
    scope_ref = budget_scope_ref(currency)
    async with async_session_factory() as session:
        repo = BudgetReservationRepository(session)
        if args.command == "create":
            snapshot = await repo.create_scope(
                budget_scope_ref=scope_ref,
                currency=currency,
                authorized_limit=args.limit,
                now=datetime.now(UTC),
            )
        else:
            snapshot = await repo.get_scope(scope_ref)
            if snapshot is None:
                raise BudgetReservationIntegrityError(f"unknown budget scope: {scope_ref}")
    return _snapshot_json(snapshot)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except BudgetReservationIntegrityError as exc:
        print(json.dumps({"error": "BUDGET_SCOPE", "detail": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
