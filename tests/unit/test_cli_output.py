"""Unit coverage of output.emit / emit_phases: projections, misses, and JSON shape."""

import json

import pytest

from claudeplans_cli.client import Reply
from claudeplans_cli.output import emit, emit_phases

_DATA = {
    "slug": "p1",
    "title": "Plan One",
    "status": "draft",
    "sections": [{"anchor": "a", "heading": "A"}, {"anchor": "b", "heading": "B"}],
    "phases": [{"slug": "a", "name": "Alpha"}, {"slug": "b", "name": "Beta"}],
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
    assert _captured(capsys)["data"] == {"slug": "b", "name": "Beta"}


def test_emit_section_miss_yields_null_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit(_REPLY, section="missing")
    assert _captured(capsys)["data"] is None


def test_emit_phase_miss_yields_null_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit(_REPLY, phase="missing")
    assert _captured(capsys)["data"] is None


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
