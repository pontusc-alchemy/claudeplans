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


def test_merge_patch_null_deletes() -> None:
    assert _merge_patch({"a": 1, "b": 2}, {"b": None}) == {"a": 1}


def test_merge_patch_dict_merges_recursively() -> None:
    assert _merge_patch({"a": {"x": 1, "y": 2}}, {"a": {"y": 3}}) == {
        "a": {"x": 1, "y": 3}
    }


def test_merge_patch_scalar_replaces() -> None:
    assert _merge_patch({"a": 1}, {"a": 2}) == {"a": 2}
