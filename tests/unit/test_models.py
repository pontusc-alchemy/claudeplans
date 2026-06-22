"""Document model invariants, extra="forbid" behavior, and the ref-unlink helper."""

import pytest
from pydantic import ValidationError

from claudeplans_contracts import (
    DocType,
    Document,
    Phase,
    unlink_research_ref,
)


def test_extra_forbidden() -> None:
    with pytest.raises(ValidationError) as exc:
        # An unknown field must reject under extra="forbid".
        Document(
            type=DocType.plan,
            project="demo",
            slug="p1",
            title="Plan One",
            owner_id="u1",
            bogus="nope",  # ty: ignore[unknown-argument]
        )
    # The errors() shape is what FastAPI serializes into a 422 body.
    err = exc.value.errors()[0]
    assert {"type", "loc", "msg", "input"} <= err.keys()


def test_research_carries_no_phases() -> None:
    with pytest.raises(ValidationError):
        Document(
            type=DocType.research,
            project="demo",
            slug="p1",
            title="Plan One",
            owner_id="u1",
            phases=[Phase(slug="x", name="X")],
        )


def test_plan_may_carry_phases() -> None:
    doc = Document(
        type=DocType.plan,
        project="demo",
        slug="p1",
        title="Plan One",
        owner_id="u1",
        phases=[Phase(slug="x", name="X")],
    )
    assert len(doc.phases) == 1


def test_primary_ref_must_be_member() -> None:
    with pytest.raises(ValidationError):
        Document(
            type=DocType.plan,
            project="demo",
            slug="p1",
            title="Plan One",
            owner_id="u1",
            primary_research_ref="r1",
        )
    doc = Document(
        type=DocType.plan,
        project="demo",
        slug="p1",
        title="Plan One",
        owner_id="u1",
        research_refs=["r1"],
        primary_research_ref="r1",
    )
    assert doc.primary_research_ref == "r1"


def test_unlink_primary_promotes_next() -> None:
    assert unlink_research_ref(["a", "b", "c"], "a", "a") == (["b", "c"], "b")


def test_unlink_primary_clears_when_empty() -> None:
    assert unlink_research_ref(["a"], "a", "a") == ([], None)


def test_unlink_non_primary_keeps_primary() -> None:
    assert unlink_research_ref(["a", "b"], "a", "b") == (["a"], "a")


def test_unlink_absent_is_noop() -> None:
    assert unlink_research_ref(["a"], "a", "z") == (["a"], "a")
