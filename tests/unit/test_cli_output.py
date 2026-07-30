"""Unit coverage of output.emit / emit_write / emit_phases: shapes and projections."""

import json

import pytest

from claudeplans_cli.client import Reply
from claudeplans_cli.output import emit, emit_phases, emit_write
from claudeplans_contracts import ValidationError

_DATA = {
    "slug": "p1",
    "title": "Plan One",
    "status": "draft",
    "sections": [{"anchor": "a", "heading": "A"}, {"anchor": "b", "heading": "B"}],
    "phases": [
        {"slug": "a", "name": "Alpha", "status": "todo", "tasks": [{"text": "t1"}]},
        {"slug": "b", "name": "Beta", "status": "done", "tasks": []},
    ],
}
_REPLY = Reply(rev="3", data=_DATA, warnings=[])


def _captured(capsys: pytest.CaptureFixture[str]) -> dict:
    out = capsys.readouterr().out
    # Single line: one trailing newline, none embedded.
    assert out.count("\n") == 1
    return json.loads(out)


def test_emit_fields_projects_to_those_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit(_REPLY, fields=["slug", "status"])
    parsed = _captured(capsys)
    assert parsed["data"] == {"slug": "p1", "status": "draft"}
    assert parsed["rev"] == "3"


def test_emit_section_returns_that_section(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit(_REPLY, section="a")
    assert _captured(capsys)["data"] == {"anchor": "a", "heading": "A"}


def test_emit_phase_returns_that_phase(capsys: pytest.CaptureFixture[str]) -> None:
    emit(_REPLY, phase="b")
    assert _captured(capsys)["data"] == {
        "slug": "b",
        "name": "Beta",
        "status": "done",
        "tasks": [],
    }


def test_emit_section_miss_raises_validation_error() -> None:
    with pytest.raises(ValidationError, match="missing"):
        emit(_REPLY, section="missing")


def test_emit_phase_miss_raises_validation_error() -> None:
    with pytest.raises(ValidationError, match="missing"):
        emit(_REPLY, phase="missing")


def test_emit_with_none_data_does_not_crash(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit(Reply(rev=None, data=None, warnings=[]))
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["data"] is None


def test_emit_phases_returns_phases_list(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_phases(_REPLY)
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    parsed = json.loads(out)
    assert parsed["rev"] == "3"
    assert parsed["phases"] == _DATA["phases"]
    assert "warnings" in parsed


# --- emit_write unit tests ---


def test_emit_write_generic_default_prints_rev_warnings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_write(_REPLY)
    parsed = _captured(capsys)
    assert parsed == {"rev": "3", "warnings": []}
    assert "data" not in parsed


def test_emit_write_full_prints_full_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_write(_REPLY, full=True)
    parsed = _captured(capsys)
    assert parsed["data"] == _DATA
    assert parsed["rev"] == "3"
    assert "warnings" in parsed


def test_emit_write_create_slice_prints_slug(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_write(_REPLY, slice_="create")
    parsed = _captured(capsys)
    assert parsed["slug"] == "p1"
    assert parsed["rev"] == "3"
    assert "data" not in parsed


def test_emit_write_phase_slice_prints_affected_tasks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_write(_REPLY, slice_="phase:a")
    parsed = _captured(capsys)
    assert parsed["phase"]["slug"] == "a"
    assert parsed["phase"]["tasks"] == [{"text": "t1"}]
    assert "data" not in parsed


def test_emit_write_phases_ordering_slice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_write(_REPLY, slice_="phases-ordering")
    parsed = _captured(capsys)
    assert parsed["phases"] == [
        {"slug": "a", "status": "todo"},
        {"slug": "b", "status": "done"},
    ]
    assert "data" not in parsed


def test_emit_write_create_full_prints_full_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # full=True overrides the slice directive.
    emit_write(_REPLY, full=True, slice_="create")
    parsed = _captured(capsys)
    assert parsed["data"] == _DATA


_OUTLINE_DATA = {
    "slug": "p1",
    "type": "plan",
    "title": "Plan One",
    "status": "draft",
    "description": "a description",
    "primary_research_ref": "r1",
    "research_refs": ["r1", "r2"],
    "sections": [
        {
            "anchor": "intro",
            "heading": "Intro",
            "level": 2,
            "placement": "lead",
            "body": "a very long body " * 200,
        },
        {
            "anchor": "outro",
            "heading": "Outro",
            "level": 3,
            "placement": "trail",
            "body": "more prose " * 200,
        },
    ],
    "phases": [
        {
            "slug": "a",
            "name": "Alpha",
            "status": "doing",
            "intro": "phase prose " * 100,
            "tasks": [
                {"text": "t1", "checked": True},
                {"text": "t2", "checked": False},
                {"text": "t3", "checked": True},
            ],
        }
    ],
}


def test_emit_outline_keeps_structure_and_drops_prose(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit(Reply(rev="7", data=_OUTLINE_DATA, warnings=[]), outline=True)
    data = _captured(capsys)["data"]
    assert data["sections"] == [
        {"anchor": "intro", "heading": "Intro", "level": 2, "placement": "lead"},
        {"anchor": "outro", "heading": "Outro", "level": 3, "placement": "trail"},
    ]
    assert data["phases"] == [
        {
            "slug": "a",
            "name": "Alpha",
            "status": "doing",
            "tasks": {"total": 3, "checked": 2},
        }
    ]
    assert data["primary_research_ref"] == "r1"
    assert data["research_refs"] == ["r1", "r2"]


def test_emit_outline_carries_no_prose_anywhere(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The whole point is that the body never reaches the reader. A key added to
    # Section or Phase later must not silently start smuggling prose through.
    emit(Reply(rev="7", data=_OUTLINE_DATA, warnings=[]), outline=True)
    raw = capsys.readouterr().out
    assert "a very long body" not in raw
    assert "phase prose" not in raw
    assert "a description" not in raw
    assert len(raw) < 400


def test_emit_outline_states_render_order_not_just_membership(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # placement decides whether a section renders before or after the phases, so an
    # outline without it describes a document that renders in a different order.
    emit(Reply(rev="7", data=_OUTLINE_DATA, warnings=[]), outline=True)
    placements = [s["placement"] for s in _captured(capsys)["data"]["sections"]]
    assert placements == ["lead", "trail"]


def test_emit_outline_on_a_doc_with_no_structure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A research doc has no phases; the keys are still present so a reader branches
    # on emptiness, never on key presence.
    emit(
        Reply(rev="1", data={"slug": "r1", "type": "research"}, warnings=[]),
        outline=True,
    )
    data = _captured(capsys)["data"]
    assert data["sections"] == [] and data["phases"] == []
    assert data["research_refs"] == []
    assert data["primary_research_ref"] is None
