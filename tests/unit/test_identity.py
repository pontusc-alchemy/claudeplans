"""Pure identity helpers: deterministic uid minting and slugify."""

import uuid

import pytest

from claudeplans.auth.identity import mint_uid, slugify


def test_mint_uid_is_deterministic() -> None:
    assert mint_uid("alice") == mint_uid("alice")


def test_mint_uid_is_case_and_whitespace_insensitive() -> None:
    base = mint_uid("dev")
    assert mint_uid("Dev") == base
    assert mint_uid(" dev ") == base


def test_mint_uid_differs_by_name() -> None:
    assert mint_uid("alice") != mint_uid("bob")


def test_mint_uid_parses_as_uuid() -> None:
    uuid.UUID(mint_uid("alice"))


def test_slugify_basic() -> None:
    assert slugify("Alice Smith") == "alice-smith"


def test_slugify_collapses_runs() -> None:
    assert slugify("a__b") == "a-b"
    assert slugify("a  b") == "a-b"


def test_slugify_strips_edges() -> None:
    assert slugify("--Hi!--") == "hi"


def test_slugify_empty_raises() -> None:
    with pytest.raises(ValueError):
        slugify("")


def test_slugify_punctuation_only_raises() -> None:
    with pytest.raises(ValueError):
        slugify("!!!")
