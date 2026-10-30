"""Independent arithmetic checks for the engineering data audit.

Diploma printed integers are NOT treated as exact outputs of the formula.
"""
import math

import pytest

from core.melting.metal_balance import calc_metal_charge


@pytest.mark.parametrize(
    ("good_t", "lps_t", "reject_t", "loss_pct"),
    [(37000.0, 16320.0, 2666.0, 5.0),
     (64000.0, 22400.0, 4320.0, 5.0)],
)
def test_charge_matches_mass_balance_not_diploma_rounding(
    good_t, lps_t, reject_t, loss_pct
):
    actual = calc_metal_charge(
        good_t,
        brak_pct=100.0 * reject_t / good_t,
        litniki_pribyli_pct=100.0 * lps_t / good_t,
        ugar_pct=loss_pct,
    )
    assert math.isclose(
        actual * (1.0 - loss_pct / 100.0),
        good_t + lps_t + reject_t,
        rel_tol=1e-12,
    )


@pytest.mark.parametrize(
    ("good_t", "reject_pct", "lps_pct", "loss_pct"),
    [(float("nan"), 5, 25, 5),
     (100, float("inf"), 25, 5),
     (100, 5, -1, 5),
     (100, 5, 25, 100),
     (-1, 5, 25, 5)],
)
def test_invalid_charge_inputs_are_rejected(
    good_t, reject_pct, lps_pct, loss_pct
):
    with pytest.raises(ValueError):
        calc_metal_charge(good_t, reject_pct, lps_pct, loss_pct)


def test_charge_zero_output_is_zero():
    assert calc_metal_charge(0, 5, 25, 5) == 0.0
