"""Pure delta transforms: happy paths, domain ValidationError cases, immutability."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from claudeplans import deltas
from claudeplans.deltas import _merge_patch
from claudeplans_contracts import (
    DocStatus,
    DocType,
    Document,
    Phase,
    PhaseStatus,
    Section,
    SectionPlacement,
    Task,
    ValidationError,
)


def _doc() -> Document:
    return Document(
        type=DocType.plan,
        project="demo",
        slug="p1",
        title="Plan One",
        owner_id="u1",
        sections=[Section(anchor="intro", heading="Intro", body="hello")],
        phases=[
            Phase(
                slug="a",
                name="Alpha",
                tasks=[Task(text="t1"), Task(text="t2", checked=True)],
            ),
            Phase(slug="b", name="Beta"),
        ],
    )


def _snapshot(doc: Document) -> dict:
    # A deep dump is the immutability oracle: the input must be byte-identical after.
    return doc.model_dump(mode="json")


def test_set_document_status() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.set_document_status(doc, DocStatus.active)
    assert out.status is DocStatus.active
    assert _snapshot(doc) == before


def test_add_phase_appends() -> None:
    doc = _doc()
    before = _snapshot(doc)
    appended = deltas.add_phase(doc, "c", "Gamma", PhaseStatus.todo)
    assert [p.slug for p in appended.phases] == ["a", "b", "c"]
    assert _snapshot(doc) == before


def test_add_phase_duplicate_slug_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.add_phase(_doc(), "a", "Dup", PhaseStatus.todo)


def test_add_phase_with_prose_fields() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.add_phase(
        doc,
        "p2",
        "Name",
        PhaseStatus.todo,
        intro="I",
        exit_criteria="E",
        notes="N",
    )
    phase = next(p for p in out.phases if p.slug == "p2")
    assert phase.intro == "I"
    assert phase.exit_criteria == "E"
    assert phase.notes == "N"
    assert _snapshot(doc) == before


def test_add_phase_default_prose_is_empty() -> None:
    out = deltas.add_phase(_doc(), "p2", "Name", PhaseStatus.todo)
    phase = next(p for p in out.phases if p.slug == "p2")
    assert phase.intro == ""
    assert phase.exit_criteria == ""
    assert phase.notes == ""


def test_set_phase_status() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.set_phase_status(doc, "a", PhaseStatus.doing)
    assert out.phases[0].status is PhaseStatus.doing
    assert _snapshot(doc) == before


def test_set_phase_status_missing_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.set_phase_status(_doc(), "zzz", PhaseStatus.doing)


def test_move_phase() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.move_phase(doc, "b", 0)
    assert [p.slug for p in out.phases] == ["b", "a"]
    assert _snapshot(doc) == before


def test_move_phase_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.move_phase(_doc(), "a", 5)


def test_move_phase_missing_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.move_phase(_doc(), "zzz", 0)


def test_add_phase_at_inserts_at_index() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.add_phase(doc, "c", "Gamma", PhaseStatus.todo, at=0)
    assert [p.slug for p in out.phases] == ["c", "a", "b"]
    assert _snapshot(doc) == before


def test_add_phase_at_none_appends() -> None:
    out = deltas.add_phase(_doc(), "c", "Gamma", PhaseStatus.todo, at=None)
    assert [p.slug for p in out.phases] == ["a", "b", "c"]


def test_add_phase_at_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.add_phase(_doc(), "c", "Gamma", PhaseStatus.todo, at=99)


def test_add_phase_at_len_appends() -> None:
    # at == len(phases) is the inclusive upper bound: it appends, same as at=None.
    doc = _doc()  # 2 phases
    out = deltas.add_phase(doc, "c", "Gamma", PhaseStatus.todo, at=len(doc.phases))
    assert [p.slug for p in out.phases] == ["a", "b", "c"]


def test_remove_phase() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.remove_phase(doc, "a")
    assert [p.slug for p in out.phases] == ["b"]
    assert _snapshot(doc) == before


def test_remove_phase_missing_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.remove_phase(_doc(), "zzz")


def test_add_task_appends() -> None:
    doc = _doc()
    before = _snapshot(doc)
    appended = deltas.add_task(doc, "a", "t3")
    assert [t.text for t in appended.phases[0].tasks] == ["t1", "t2", "t3"]
    assert _snapshot(doc) == before


def test_add_task_missing_phase_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.add_task(_doc(), "zzz", "t")


def test_toggle_task_absolute() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.toggle_task(doc, "a", 0, True)
    assert out.phases[0].tasks[0].checked is True
    # Re-applying the same absolute value is idempotent (re-apply safety).
    again = deltas.toggle_task(out, "a", 0, True)
    assert again.phases[0].tasks[0].checked is True
    assert _snapshot(doc) == before


def test_toggle_task_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.toggle_task(_doc(), "a", 9, True)


def test_toggle_task_sets_absolute_not_flip() -> None:
    # Task index 1 starts checked=True in _doc(); setting False yields False (a flip
    # would return True). Proves the absolute set that `set-checked` relies on.
    out = deltas.toggle_task(_doc(), "a", 1, False)
    assert out.phases[0].tasks[1].checked is False


def test_edit_task() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.edit_task(doc, "a", 0, "renamed")
    assert out.phases[0].tasks[0].text == "renamed"
    assert _snapshot(doc) == before


def test_edit_task_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.edit_task(_doc(), "a", 9, "x")


def test_remove_task() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.remove_task(doc, "a", 0)
    assert [t.text for t in out.phases[0].tasks] == ["t2"]
    assert _snapshot(doc) == before


def test_remove_task_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.remove_task(_doc(), "a", 9)


def test_add_section_appends() -> None:
    doc = _doc()
    before = _snapshot(doc)
    appended = deltas.add_section(doc, "ctx", "Context", "body", 2)
    assert [s.anchor for s in appended.sections] == ["intro", "ctx"]
    assert _snapshot(doc) == before


def test_add_section_duplicate_anchor_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.add_section(_doc(), "intro", "Dup", "", 2)


def test_set_section_only_provided_fields() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.set_section(doc, "intro", heading="New", body=None, level=None)
    assert out.sections[0].heading == "New"
    # body/level were None, so they are left unchanged.
    assert out.sections[0].body == "hello"
    assert out.sections[0].level == 2
    assert _snapshot(doc) == before


def test_set_section_missing_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.set_section(_doc(), "zzz", heading="x", body=None, level=None)


def test_patch_section_scalar_replace() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.patch_section(doc, "intro", {"body": "replaced"})
    assert out.sections[0].body == "replaced"
    assert _snapshot(doc) == before


def test_patch_section_null_on_required_field_raises() -> None:
    # Nulling a required Section field (heading) violates the schema on re-validate.
    with pytest.raises(PydanticValidationError):
        deltas.patch_section(_doc(), "intro", {"heading": None})


def test_patch_section_missing_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.patch_section(_doc(), "zzz", {"body": "x"})


def test_remove_section() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.remove_section(doc, "intro")
    assert out.sections == []
    assert _snapshot(doc) == before


def test_remove_section_missing_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.remove_section(_doc(), "zzz")


def test_put_research_refs() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.put_research_refs(doc, ["r1", "r2"], "r1")
    assert out.research_refs == ["r1", "r2"]
    assert out.primary_research_ref == "r1"
    assert _snapshot(doc) == before


# --- set_phase ---------------------------------------------------------------


def test_set_phase_renames_target_leaves_others() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.set_phase(doc, "a", name="Alpha Renamed")
    assert out.phases[0].name == "Alpha Renamed"
    # phase "b" is untouched
    assert out.phases[1].name == "Beta"
    assert _snapshot(doc) == before


def test_set_phase_none_name_leaves_unchanged() -> None:
    doc = _doc()
    out = deltas.set_phase(doc, "a", name=None)
    assert out.phases[0].name == "Alpha"


def test_set_phase_missing_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.set_phase(_doc(), "zzz", name="X")


def test_set_phase_sets_prose_fields() -> None:
    doc = _doc()
    out = deltas.set_phase(
        doc,
        "a",
        name=None,
        intro="The why",
        exit_criteria="Done when",
        notes="!!! note",
    )
    phase = out.phases[0]
    assert phase.intro == "The why"
    assert phase.exit_criteria == "Done when"
    assert phase.notes == "!!! note"
    # name was None -> unchanged.
    assert phase.name == doc.phases[0].name


def test_set_phase_none_prose_leaves_unchanged() -> None:
    seeded = deltas.set_phase(_doc(), "a", name=None, intro="keep")
    out = deltas.set_phase(seeded, "a", name=None)
    assert out.phases[0].intro == "keep"


def test_set_phase_empty_string_clears_prose() -> None:
    seeded = deltas.set_phase(_doc(), "a", name=None, intro="something")
    out = deltas.set_phase(seeded, "a", name=None, intro="")
    assert out.phases[0].intro == ""


# --- move_section ------------------------------------------------------------


def test_move_section_reorders() -> None:
    doc = _doc()
    # Add a second section so we have something to move.
    doc2 = deltas.add_section(doc, "ctx", "Context", "body", 2)
    before = _snapshot(doc2)
    out = deltas.move_section(doc2, "ctx", 0)
    assert [s.anchor for s in out.sections] == ["ctx", "intro"]
    assert _snapshot(doc2) == before


def test_move_section_out_of_range_raises() -> None:
    doc = _doc()
    doc2 = deltas.add_section(doc, "ctx", "Context", "body", 2)
    with pytest.raises(ValidationError):
        deltas.move_section(doc2, "intro", 5)


def test_move_section_missing_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.move_section(_doc(), "zzz", 0)


# --- add_task / add_section with --at ----------------------------------------


def test_add_task_at_inserts_at_index() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.add_task(doc, "a", "t0", at=0)
    assert [t.text for t in out.phases[0].tasks] == ["t0", "t1", "t2"]
    assert _snapshot(doc) == before


def test_add_task_at_none_appends() -> None:
    doc = _doc()
    out = deltas.add_task(doc, "a", "t3", at=None)
    assert [t.text for t in out.phases[0].tasks] == ["t1", "t2", "t3"]


def test_add_task_at_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.add_task(_doc(), "a", "x", at=99)


def test_add_task_at_len_appends() -> None:
    # at == len(tasks) is the inclusive upper bound: it appends, same as at=None.
    doc = _doc()  # phase "a" has 2 tasks
    out = deltas.add_task(doc, "a", "t3", at=len(doc.phases[0].tasks))
    assert [t.text for t in out.phases[0].tasks] == ["t1", "t2", "t3"]


def test_add_task_checked_true_sets_checked() -> None:
    # Passing checked=True should create the task with checked=True.
    out = deltas.add_task(_doc(), "a", "t", checked=True)
    assert out.phases[0].tasks[-1].checked is True


def test_add_task_checked_default_is_false() -> None:
    # Omitting checked (the default) should create the task with checked=False.
    out = deltas.add_task(_doc(), "a", "t")
    assert out.phases[0].tasks[-1].checked is False


def test_add_section_at_inserts_at_index() -> None:
    doc = _doc()
    doc2 = deltas.add_section(doc, "ctx", "Context", "body", 2)
    before = _snapshot(doc2)
    out = deltas.add_section(doc2, "new", "New", "", 2, at=0)
    assert [s.anchor for s in out.sections] == ["new", "intro", "ctx"]
    assert _snapshot(doc2) == before


def test_add_section_at_none_appends() -> None:
    doc = _doc()
    out = deltas.add_section(doc, "ctx", "Context", "body", 2, at=None)
    assert [s.anchor for s in out.sections] == ["intro", "ctx"]


def test_add_section_at_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        deltas.add_section(_doc(), "new", "New", "", 2, at=99)


# --- set_document_meta -------------------------------------------------------


def test_set_document_meta_sets_provided_fields() -> None:
    doc = _doc()
    before = _snapshot(doc)
    out = deltas.set_document_meta(
        doc,
        title="New Title",
        description="A description",
        date=None,
        frontmatter=None,
    )
    assert out.title == "New Title"
    assert out.description == "A description"
    # date and frontmatter were None so they are left unchanged
    assert out.date == doc.date
    assert _snapshot(doc) == before


def test_set_document_meta_leaves_omitted_unchanged() -> None:
    doc = _doc()
    out1 = deltas.set_document_meta(
        doc,
        title="T1",
        description="D1",
        date=None,
        frontmatter=None,
    )
    out2 = deltas.set_document_meta(
        out1,
        title="T2",
        description=None,
        date=None,
        frontmatter=None,
    )
    assert out2.title == "T2"
    # description was None on the second call — left as "D1"
    assert out2.description == "D1"


def test_set_document_meta_frontmatter() -> None:
    doc = _doc()
    out = deltas.set_document_meta(
        doc,
        title=None,
        description=None,
        date=None,
        frontmatter={"key": "val"},
    )
    assert out.frontmatter == {"key": "val"}


def test_set_document_meta_frontmatter_replaces_whole_dict() -> None:
    # Providing frontmatter is an absolute REPLACE, not a merge: seed {"a":1}, set
    # {"b":2} -> exactly {"b":2} (distinguishes it from section patch's merge-patch).
    seeded = _doc().model_copy(update={"frontmatter": {"a": 1}})
    out = deltas.set_document_meta(
        seeded, title=None, description=None, date=None, frontmatter={"b": 2}
    )
    assert out.frontmatter == {"b": 2}


def test_merge_patch_null_deletes() -> None:
    assert _merge_patch({"a": 1, "b": 2}, {"b": None}) == {"a": 1}


def test_merge_patch_dict_merges_recursively() -> None:
    assert _merge_patch({"a": {"x": 1, "y": 2}}, {"a": {"y": 3}}) == {
        "a": {"x": 1, "y": 3}
    }


def test_merge_patch_scalar_replaces() -> None:
    assert _merge_patch({"a": 1}, {"a": 2}) == {"a": 2}


# --- section placement -------------------------------------------------------


def test_add_section_defaults_placement_lead() -> None:
    out = deltas.add_section(_doc(), "ctx", "Context", "body", 2)
    added = next(s for s in out.sections if s.anchor == "ctx")
    assert added.placement is SectionPlacement.lead


def test_add_section_placement_trail() -> None:
    out = deltas.add_section(
        _doc(), "ctx", "Context", "body", 2, placement=SectionPlacement.trail
    )
    added = next(s for s in out.sections if s.anchor == "ctx")
    assert added.placement is SectionPlacement.trail


def test_set_section_updates_placement() -> None:
    doc = deltas.add_section(_doc(), "ctx", "Context", "body", 2)
    out = deltas.set_section(
        doc,
        "ctx",
        heading=None,
        body=None,
        level=None,
        placement=SectionPlacement.trail,
    )
    assert next(s for s in out.sections if s.anchor == "ctx").placement is (
        SectionPlacement.trail
    )


def test_set_section_none_placement_leaves_unchanged() -> None:
    doc = deltas.add_section(
        _doc(), "ctx", "Context", "body", 2, placement=SectionPlacement.trail
    )
    out = deltas.set_section(doc, "ctx", heading="New", body=None, level=None)
    assert next(s for s in out.sections if s.anchor == "ctx").placement is (
        SectionPlacement.trail
    )
