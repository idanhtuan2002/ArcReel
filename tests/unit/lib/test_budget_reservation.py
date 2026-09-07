"""Typed Host budget authorization domain tests."""

from decimal import Decimal

import pytest


def test_money_validators_reject_out_of_range_values() -> None:
    from lib.budget_reservation import require_nonnegative_money, require_positive_money

    with pytest.raises(ValueError, match="authorized_limit"):
        require_nonnegative_money(Decimal("-0.01"), field_name="authorized_limit")
    with pytest.raises(ValueError, match="reserved_amount"):
        require_positive_money(Decimal("0"), field_name="reserved_amount")


def test_money_validators_preserve_decimal_values() -> None:
    from lib.budget_reservation import require_nonnegative_money, require_positive_money

    assert require_nonnegative_money(Decimal("0"), field_name="authorized_limit") == Decimal("0")
    assert require_positive_money(Decimal("1.250000"), field_name="reserved_amount") == Decimal("1.250000")


def test_money_validators_reject_binary_float() -> None:
    from lib.budget_reservation import require_nonnegative_money

    with pytest.raises(TypeError, match="Decimal"):
        require_nonnegative_money(0.1, field_name="authorized_limit")


def test_reservation_state_has_the_fixed_vocabulary() -> None:
    from lib.budget_reservation import BudgetReservationState

    assert BudgetReservationState("ACTIVE") is BudgetReservationState.ACTIVE
    assert {state.value for state in BudgetReservationState} == {
        "ACTIVE",
        "CLAIMED",
        "RELEASED",
        "EXPIRED",
    }
