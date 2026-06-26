"""Document model invariants, extra="forbid" behavior, and the ref-unlink helper."""

import pytest
from pydantic import ValidationError

from claudeplans_contracts import (
    DocType,
    Document,
    Phase,
    Section,
    SectionPlacement,
    Task,
    unlink_research_ref,
)
from claudeplans_contracts.models import validate_anchor, validate_text_field


def _doc(
    *,
    title: str = "Plan One",
    description: str | None = None,
    phases: list[Phase] | None = None,
    sections: list[Section] | None = None,
) -> Document:
    return Document(
        type=DocType.plan,
        project="demo",
        slug="p1",
        title=title,
        owner_id="u1",
        description=description,
        phases=phases or [],
        sections=sections or [],
    )


# Empty, whitespace-only, and line-break/control-char content is rejected on every
# single-line field; `body` (multi-line markdown) is exempt. Line breaks include the
# Unicode separators U+2028/U+2029 and NEL (U+0085), not just ASCII.
_BAD_TEXT = [
    "",
    "   ",
    "\t",
    "line\nbreak",
    "tab\there",
    "bell\x07",
    "lsep\u2028x",
    "psep\u2029x",
    "nel\x85x",
]


@pytest.mark.parametrize("bad", _BAD_TEXT)
def test_task_text_rejects_bad_content(bad: str) -> None:
    with pytest.raises(ValidationError):
        Task(text=bad)


@pytest.mark.parametrize("bad", _BAD_TEXT)
def test_section_heading_rejects_bad_content(bad: str) -> None:
    with pytest.raises(ValidationError):
        Section(anchor="a", heading=bad)


@pytest.mark.parametrize("bad", _BAD_TEXT)
def test_phase_name_rejects_bad_content(bad: str) -> None:
    with pytest.raises(ValidationError):
        Phase(slug="a", name=bad)


@pytest.mark.parametrize("bad", _BAD_TEXT)
def test_document_title_rejects_bad_content(bad: str) -> None:
    with pytest.raises(ValidationError):
        _doc(title=bad)


@pytest.mark.parametrize("bad", _BAD_TEXT)
def test_document_description_rejects_bad_content(bad: str) -> None:
    with pytest.raises(ValidationError):
        _doc(description=bad)


def test_document_description_none_is_allowed() -> None:
    assert _doc(description=None).description is None


def test_section_body_allows_multiline() -> None:
    # body is raw markdown — line breaks must be preserved, not rejected.
    s = Section(anchor="a", heading="H", body="para one\n\npara two")
    assert "\n" in s.body


# Path-corrupting / reserved / route-breaking identifiers are rejected on phase slug
# and section anchor. The allowlist is [A-Za-z0-9_-], so URL metacharacters (#, ?,
# space, %, :) and embedded dots (which would make the `phases.<slug>` locator
# ambiguous) reject too — not just '/', '.', '..', '@'-prefix, and control chars.
_BAD_ANCHORS = [
    "",
    "a/b",
    ".",
    "..",
    "@end",
    "@0",
    "bad\nanchor",
    "tab\there",
    "has space",
    "frag#ment",
    "query?x",
    "colon:x",
    "v1.2",
    "per%cent",
]

# Legitimate identifiers — letters, digits, hyphen, underscore — are accepted.
_GOOD_ANCHORS = ["a", "out-of-scope", "phase_1", "v1", "ABC123"]


@pytest.mark.parametrize("bad", _BAD_ANCHORS)
def test_section_anchor_rejects_bad_identifier(bad: str) -> None:
    with pytest.raises(ValidationError):
        Section(anchor=bad, heading="H")


@pytest.mark.parametrize("bad", _BAD_ANCHORS)
def test_phase_slug_rejects_bad_identifier(bad: str) -> None:
    with pytest.raises(ValidationError):
        Phase(slug=bad, name="N")


@pytest.mark.parametrize("good", _GOOD_ANCHORS)
def test_anchor_and_slug_accept_clean_identifiers(good: str) -> None:
    assert Section(anchor=good, heading="H").anchor == good
    assert Phase(slug=good, name="N").slug == good


def test_validate_text_field_names_the_field() -> None:
    with pytest.raises(ValueError, match="task text"):
        validate_text_field("", field="task text")


def test_validate_anchor_at_prefix_message_points_at_append() -> None:
    # The '@end' footgun: the message must name the offender and explain append order.
    with pytest.raises(ValueError, match=r"@end.*appended in order"):
        validate_anchor("@end", field="section anchor")


def test_duplicate_phase_slug_error_names_offender() -> None:
    with pytest.raises(ValidationError, match="duplicate phase slug 'x'"):
        _doc(phases=[Phase(slug="x", name="X"), Phase(slug="x", name="X2")])


def test_duplicate_section_anchor_error_names_offender() -> None:
    dupes = [Section(anchor="a", heading="H"), Section(anchor="a", heading="H2")]
    with pytest.raises(ValidationError, match="duplicate section anchor 'a'"):
        _doc(sections=dupes)


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


def test_unlink_mid_list_primary_promotes_first() -> None:
    # Removing a mid-list primary promotes the FIRST remaining ref (list head),
    # not the element that followed it.
    assert unlink_research_ref(["a", "b", "c"], "b", "b") == (["a", "c"], "a")


def test_section_level_out_of_range_rejected() -> None:
    # level becomes <h{level}>; nh3 strips <h0>/<h7+>, silently dropping the heading,
    # so the bound rejects out-of-range at the contract boundary.
    for bad in (0, 9):
        with pytest.raises(ValidationError):
            Section(anchor="a", heading="H", level=bad)


def test_duplicate_phase_slugs_rejected() -> None:
    with pytest.raises(ValidationError):
        Document(
            type=DocType.plan,
            project="demo",
            slug="p1",
            title="Plan One",
            owner_id="u1",
            phases=[Phase(slug="x", name="X"), Phase(slug="x", name="X2")],
        )


# --- Phase prose fields ---


def test_phase_prose_defaults_are_empty() -> None:
    # Bare Phase carries empty strings for all three prose fields.
    p = Phase(slug="x", name="X")
    assert p.intro == ""
    assert p.exit_criteria == ""
    assert p.notes == ""


def test_phase_prose_accepts_multiline_and_empty() -> None:
    # Unlike single-line fields (name, task text), prose fields are raw markdown:
    # empty strings and embedded newlines are valid and round-trip unchanged.
    p = Phase(
        slug="x",
        name="X",
        intro="line one\n\nline two",
        exit_criteria="",
        notes="!!! note\n    body",
    )
    assert p.intro == "line one\n\nline two"
    assert p.exit_criteria == ""
    assert p.notes == "!!! note\n    body"


# --- Section.placement ---


def test_section_default_placement_is_lead() -> None:
    s = Section(anchor="a", heading="H")
    assert s.placement is SectionPlacement.lead


def test_section_placement_trail_round_trips() -> None:
    s = Section(anchor="a", heading="H", placement=SectionPlacement.trail)
    assert s.placement is SectionPlacement.trail


def test_section_placement_model_dump_serializes_to_string() -> None:
    # model_dump() must produce the plain string "trail", not the enum member,
    # so storage / wire serialisation doesn't leak enum repr.
    s = Section(anchor="a", heading="H", placement=SectionPlacement.trail)
    dumped = s.model_dump()
    assert dumped["placement"] == "trail"


def test_section_placement_model_validate_round_trips() -> None:
    # A raw dict with placement="trail" must parse back to the enum member.
    raw = {"anchor": "a", "heading": "H", "placement": "trail"}
    s = Section.model_validate(raw)
    assert s.placement is SectionPlacement.trail


# --- SectionPlacement StrEnum ---


def test_section_placement_str_equality() -> None:
    # StrEnum: members compare equal to their string value.
    assert SectionPlacement.lead == "lead"
    assert SectionPlacement.trail == "trail"


def test_section_placement_construct_from_string() -> None:
    assert SectionPlacement("trail") is SectionPlacement.trail
    assert SectionPlacement("lead") is SectionPlacement.lead
