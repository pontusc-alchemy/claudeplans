"""Storage-key derivation and the key-segment / research-ref field validators."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from claudeplans_contracts import (
    DocType,
    Document,
    document_key,
    key_for_document,
)


def _doc() -> Document:
    return Document(
        type=DocType.plan,
        project="demo",
        slug="p1",
        title="Plan One",
        owner_id="u1",
    )


def test_document_key_layout() -> None:
    assert document_key("u1", "demo", "p1") == "u1/demo/p1"


def test_key_for_document_matches_derivation() -> None:
    assert key_for_document(_doc()) == "u1/demo/p1"


@pytest.mark.parametrize("field", ["owner_id", "project", "slug"])
@pytest.mark.parametrize("bad", ["", "a/b", ".."])
def test_key_segments_reject_unsafe_values(field: str, bad: str) -> None:
    # Empty, "/"-bearing, and ".." segments would break key derivation or let a key
    # escape its directory, so the model must reject them at the boundary.
    fields: dict[str, str] = {"owner_id": "u1", "project": "demo", "slug": "p1"}
    fields[field] = bad
    with pytest.raises(PydanticValidationError):
        Document(
            type=DocType.plan,
            title="Plan One",
            owner_id=fields["owner_id"],
            project=fields["project"],
            slug=fields["slug"],
        )


def test_research_refs_dedup_preserves_order() -> None:
    doc = Document(
        type=DocType.plan,
        project="demo",
        slug="p1",
        title="Plan One",
        owner_id="u1",
        research_refs=["a", "b", "a"],
    )
    assert doc.research_refs == ["a", "b"]


def test_primary_ref_validates_against_deduped_refs() -> None:
    # The duplicate is dropped before the primary-membership invariant runs, so a
    # primary that survives the dedup still validates.
    doc = Document(
        type=DocType.plan,
        project="demo",
        slug="p1",
        title="Plan One",
        owner_id="u1",
        research_refs=["a", "b", "a"],
        primary_research_ref="b",
    )
    assert doc.research_refs == ["a", "b"]
    assert doc.primary_research_ref == "b"
