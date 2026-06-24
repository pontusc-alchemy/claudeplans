"""Validate hand-authored JSON fixtures against the full Document model.

Each file under tests/fixtures/*.json must round-trip through the same
migrate_document path the server uses: migrate() upgrades the stored dict to the
current schema version, then Document.model_validate() enforces all invariants.
"""

import json
from pathlib import Path

import pytest

from claudeplans_contracts.migrate import migrate_document
from claudeplans_contracts.models import Document

_FIXTURES = sorted((Path(__file__).parent.parent / "fixtures").glob("*.json"))


def test_fixtures_present() -> None:
    # Guard: an empty glob would silently pass the parametrized test below.
    assert _FIXTURES


@pytest.mark.parametrize("path", _FIXTURES, ids=lambda p: p.stem)
def test_fixture_is_valid_document(path: Path) -> None:
    raw = json.loads(path.read_text())
    doc = migrate_document(raw)
    assert isinstance(doc, Document)
    # Round-trip: serialise back to JSON-safe dict, re-validate, and assert stability.
    reloaded = Document.model_validate(doc.model_dump(mode="json"))
    assert reloaded.model_dump(mode="json") == doc.model_dump(mode="json")
