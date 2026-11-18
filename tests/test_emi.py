import pytest

from utils.emi_calculator import (
    calculate_emi, estimate_stamp_duty, estimate_gst, total_cost_breakdown, format_inr,
)


def test_emi_known_value():
    # ₹40L @ 8.5% for 20 years — standard bank calculators give ≈ ₹34,713/month
    r = calculate_emi(4_000_000, 8.5, 20)
    assert r["emi"] == pytest.approx(34_713, abs=2)
    assert r["months"] == 240
    assert r["total_payment"] == pytest.approx(r["emi"] * 240, abs=240)
    assert r["total_interest"] == r["total_payment"] - r["principal"]


def test_emi_zero_rate():
    r = calculate_emi(1_200_000, 0, 10)
    assert r["emi"] == 10_000
    assert r["total_interest"] == 0


def test_stamp_duty_by_state():
    tn = estimate_stamp_duty(10_000_000, "Tamil Nadu")
    assert tn["stamp_duty"] == 700_000 and tn["registration"] == 100_000
    mp = estimate_stamp_duty(10_000_000, "Madhya Pradesh")
    assert mp["stamp_rate"] == 7.5 and mp["reg_rate"] == 3.0
    unknown = estimate_stamp_duty(10_000_000, "Atlantis")
    assert unknown["stamp_rate"] == 5.0


@pytest.mark.parametrize("price, uc, expected", [
    (4_000_000, False, 0),          # ready-to-move: no GST
    (9_000_000, False, 0),
    (4_000_000, True, 40_000),      # affordable under-construction: 1%
    (9_000_000, True, 450_000),     # other under-construction: 5%
])
def test_gst(price, uc, expected):
    assert estimate_gst(price, uc) == expected


def test_total_cost_breakdown():
    r = total_cost_breakdown(5_000_000, 80, 8.5, 20, "Karnataka")
    assert r["down_payment"] == 1_000_000
    assert r["loan_amount"] == 4_000_000
    assert r["gst"] == 0
    assert r["move_in_cost"] == 1_000_000 + r["total_charges"]


@pytest.mark.parametrize("amount, expected", [
    (25_000_000, "₹2.50 Cr"),
    (4_500_000, "₹45.00 L"),
    (18_500, "₹18,500"),
])
def test_format_inr(amount, expected):
    assert format_inr(amount) == expected
