"""Unit tests for core value-parsing helpers (offline, no network)."""

import pytest

from chemfacts.core import _comparable, _first_number, _to_celsius


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1.03", 1.03),
        ("1.03 at 77 \u00b0F", 1.03),
        ("1.027 @25 \u00b0C", 1.027),
        ("-67 \u00b0C", -67.0),
        ("Relative density (water = 1): 1.03", 1.03),
        ("at 1.33kPa: 158 \u00b0C", 158.0),
        ("Density: 1.0225", 1.0225),
        ("23 \u00b0C", 23.0),
    ],
)
def test_first_number(raw, expected):
    assert _first_number(raw) == expected


def test_first_number_no_number():
    assert _first_number("n/a") is None


@pytest.mark.parametrize(
    "raw, heading, expected",
    [
        # plain values pass through
        ("1.03", "Density", 1.03),
        ("23 \u00b0C", "Flash Point", 23.0),
        # qualified / range values are excluded
        ("greater than 200 \u00b0F (NTP, 1992)", "Flash Point", None),
        ("Approximately -60 \u00b0C", "Melting Point", None),
        ("0.5 g/mol calculated", "Boiling Point", None),
        # sub-atmospheric pressure values are excluded (different conditions)
        ("BP: 158 \u00b0C at 10 torr", "Boiling Point", None),
        ("316 \u00b0F at 10 mmHg (NTP, 1992)", "Boiling Point", None),
        ("at 1.33kPa: 158 \u00b0C", "Boiling Point", None),
        # atmospheric values stay
        ("360 \u00b0C @760 [mm Hg]", "Boiling Point", 360.0),
        # Fahrenheit is normalized to Celsius for temperature properties
        ("-76 \u00b0F", "Melting Point", -60.0),
    ],
)
def test_comparable(raw, heading, expected):
    assert _comparable(raw, heading) == expected


@pytest.mark.parametrize(
    "raw, heading, expected",
    [
        ("23 \u00b0C", "Flash Point", 23.0),
        ("74 \u00b0F", "Flash Point", 23.333),
        ("500 \u00b0F", "Boiling Point", 260.0),
    ],
)
def test_to_celsius(raw, heading, expected):
    assert _to_celsius(raw, heading) == pytest.approx(expected, abs=1e-2)
