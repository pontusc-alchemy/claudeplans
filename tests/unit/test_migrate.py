"""Upgrade-on-read migration: v0 -> current, pass-through, and no input mutation."""

import pytest

from claudeplans_contracts import (
    CURRENT_SCHEMA_VERSION,
    ValidationError,
    migrate,
    migrate_document,
)


def test_migrates_v0_to_current() -> None:
    raw = {
        "type": "plan",
        "project": "demo",
        "slug": "p1",
        "title": "Plan One",
        "owner": "u1",  # legacy key, renamed to owner_id by the migration
    }
    doc = migrate_document(raw)
    assert doc.schema_version == CURRENT_SCHEMA_VERSION
    assert doc.owner_id == "u1"
    assert doc.research_refs == []


def test_current_version_doc_unchanged() -> None:
    raw = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "type": "plan",
        "project": "demo",
        "slug": "p1",
        "title": "Plan One",
        "owner_id": "u1",
    }
    # A doc already at current must pass through untouched: no migration step runs,
    # so no defaults (e.g. research_refs) get injected.
    assert migrate(raw) == raw
    assert "research_refs" not in migrate(raw)


def test_forward_version_raises() -> None:
    raw = {
        "schema_version": 99,
        "type": "plan",
        "project": "demo",
        "slug": "p1",
        "title": "Plan One",
        "owner_id": "u1",
    }
    with pytest.raises(ValidationError):
        migrate(raw)


def test_malformed_version_raises() -> None:
    with pytest.raises(ValidationError):
        migrate({"schema_version": "oops"})


def test_migrate_does_not_mutate_input() -> None:
    raw = {"type": "plan", "owner": "u1"}
    original = dict(raw)
    migrate(raw)
    assert raw == original
