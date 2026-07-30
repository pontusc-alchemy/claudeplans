"""Storage-key derivation and the key-segment / research-ref field validators."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from claudeplans_contracts import (
    DocType,
    Document,
    document_key,
    key_for_document,
)
from claudeplans_contracts.keys import validate_key_segment

# ---------------------------------------------------------------------------
# validate_key_segment allowlist (FIX 1)
# ---------------------------------------------------------------------------

# Characters that were previously accepted by the old check but must now be
# rejected: NUL (server 500), '#'/'?' (permanently unaddressable slug),
# newline (httpx.InvalidURL on client).
_BAD_SEGMENTS = [
    "",  # empty
    "a/b",  # path separator
    "..",  # path traversal
    ".",  # path traversal
    "bad slug",  # space
    "frag#ment",  # URL fragment separator
    "query?x",  # URL query separator
    "at@sign",  # URL metachar
    "nul\x00byte",  # NUL byte → server HTTP 500
    "new\nline",  # newline → httpx.InvalidURL
    "dot.ted",  # dot ambiguous in phases.<slug> locator
]

_GOOD_SEGMENTS = ["dev", "alice", "demo", "v2-implementation", "my_project", "ABC123"]


@pytest.mark.parametrize("bad", _BAD_SEGMENTS)
def test_validate_key_segment_rejects_bad(bad: str) -> None:
    with pytest.raises(ValueError, match="invalid key segment"):
        validate_key_segment(bad)


@pytest.mark.parametrize("good", _GOOD_SEGMENTS)
def test_validate_key_segment_accepts_clean(good: str) -> None:
    assert validate_key_segment(good) == good


@pytest.mark.parametrize("field", ["owner_id", "project", "slug"])
@pytest.mark.parametrize(
    "bad",
    ["\x00", "\n", "#", "?"],
)
def test_key_segment_illegal_chars_reject_at_document_boundary(
    field: str, bad: str
) -> None:
    # These chars slipped through the old validator; the new allowlist rejects them,
    # surfacing as a pydantic ValidationError (-> HTTP 422 -> CLI exit 4).
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
        primary_parent_ref="b",
    )
    assert doc.research_refs == ["a", "b"]
    assert doc.primary_parent_ref == "b"
