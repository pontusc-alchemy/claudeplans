"""Unit coverage for `validate_rev` — the shared rev-well-formedness check.

Revs are monotonic integer-as-string counters; this pins the exact allowlist
(ASCII decimal digits only, non-empty) both server (deps.py) and CLI (client.py)
rely on via the ONE shared definition in claudeplans_contracts.
"""

import pytest

from claudeplans_contracts import InvalidRev, validate_rev

_VALID = [
    "1",
    "57",
    "12345678901234567890",  # arbitrarily large — revs are unbounded counters
    "007",  # leading zeros: accepted. validate_rev checks digit-ness, not
    # canonical form — the server never emits a leading-zero rev itself, but
    # a hand-typed or scripted --rev with one is still a well-formed integer
    # string, not a malformed client input.
]

_INVALID = [
    "",  # empty
    " 5",  # leading whitespace
    "5 ",  # trailing whitespace
    "abc",  # non-digits
    '{"rev":"5"}',  # a stray JSON blob
    "٣",  # Arabic-Indic digit three: str.isdigit() is True, isascii() is False
    "²",  # superscript two: str.isdigit() is True, isascii() is False
    'W/"5"',  # a weak ETag form
    '"5"',  # a quoted ETag form (should already be stripped by the caller)
]


@pytest.mark.parametrize("value", _VALID)
def test_validate_rev_accepts_well_formed(value: str) -> None:
    assert validate_rev(value) == value


@pytest.mark.parametrize("value", _INVALID)
def test_validate_rev_rejects_malformed(value: str) -> None:
    with pytest.raises(InvalidRev):
        validate_rev(value)
