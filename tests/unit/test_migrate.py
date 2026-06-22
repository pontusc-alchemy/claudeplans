"""Upgrade-on-read migration: v0 -> current, pass-through, and no input mutation."""

from claudeplans_contracts import (
    CURRENT_SCHEMA_VERSION,
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
    assert migrate(raw)["schema_version"] == CURRENT_SCHEMA_VERSION


def test_migrate_does_not_mutate_input() -> None:
    raw = {"type": "plan", "owner": "u1"}
    original = dict(raw)
    migrate(raw)
    assert raw == original
