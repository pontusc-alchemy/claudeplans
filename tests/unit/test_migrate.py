"""Upgrade-on-read migration: v0 -> current, pass-through, and no input mutation."""

import pytest
from pydantic import JsonValue

from claudeplans_contracts import (
    CURRENT_SCHEMA_VERSION,
    ValidationError,
    migrate,
    migrate_document,
)


def test_migrates_v0_to_current() -> None:
    raw: dict[str, JsonValue] = {
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
    raw: dict[str, JsonValue] = {
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
    raw: dict[str, JsonValue] = {
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
    raw: dict[str, JsonValue] = {"type": "plan", "owner": "u1"}
    original = dict(raw)
    migrate(raw)
    assert raw == original


def _v1_plan(**overrides: JsonValue) -> dict[str, JsonValue]:
    raw: dict[str, JsonValue] = {
        "schema_version": 1,
        "type": "plan",
        "project": "demo",
        "slug": "p1",
        "title": "Plan One",
        "owner_id": "u1",
        "research_refs": ["r1"],
        "primary_research_ref": "r1",
    }
    raw.update(overrides)
    return raw


def test_v1_renames_the_primary_ref_to_the_parent_ref() -> None:
    doc = migrate_document(_v1_plan())
    assert doc.schema_version == CURRENT_SCHEMA_VERSION
    assert doc.primary_parent_ref == "r1"


def test_v1_migration_leaves_research_refs_alone() -> None:
    """Its rename is deferred, so the two migrations cannot collide."""
    assert migrate(_v1_plan())["research_refs"] == ["r1"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"primary_research_ref": None},
        {"primary_research_ref": "gone", "research_refs": ["gone"]},
    ],
    ids=["null-primary", "dangling-primary"],
)
def test_v1_rename_is_data_independent(overrides: dict[str, JsonValue]) -> None:
    """A pure key rename: null and dangling primaries migrate 1:1, no branch."""
    out = migrate(_v1_plan(**overrides))
    assert "primary_research_ref" not in out
    assert out["primary_parent_ref"] == overrides["primary_research_ref"]


def test_v1_without_the_field_gains_no_key() -> None:
    raw = _v1_plan()
    del raw["primary_research_ref"]
    del raw["research_refs"]
    assert "primary_parent_ref" not in migrate(raw)


def test_v0_still_migrates_through_v1_to_current() -> None:
    """The chain runs every step, so v0 stores are not stranded by the v2 bump."""
    doc = migrate_document(
        {"type": "plan", "project": "d", "slug": "p", "title": "T", "owner": "u1"}
    )
    assert doc.schema_version == CURRENT_SCHEMA_VERSION
    assert doc.owner_id == "u1"
    assert doc.primary_parent_ref is None
