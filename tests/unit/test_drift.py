"""Drift linter: status/state consistency warnings, and that it never raises."""

from claudeplans.drift import lint
from claudeplans_contracts import (
    DocStatus,
    DocType,
    Document,
    Phase,
    PhaseStatus,
    Task,
)


def _doc(
    phases: list[Phase] | None = None, status: DocStatus = DocStatus.draft
) -> Document:
    return Document(
        type=DocType.plan,
        project="demo",
        slug="p1",
        title="Plan One",
        owner_id="u1",
        status=status,
        phases=phases or [],
    )


def test_clean_doc_no_warnings() -> None:
    doc = _doc(
        phases=[
            Phase(
                slug="ph1",
                name="Phase 1",
                status=PhaseStatus.done,
                tasks=[Task(text="t", checked=True)],
            )
        ]
    )
    assert lint(doc) == []


def test_done_phase_with_open_task_warns() -> None:
    doc = _doc(
        phases=[
            Phase(
                slug="ph1",
                name="Phase 1",
                status=PhaseStatus.done,
                tasks=[Task(text="t", checked=False)],
            )
        ]
    )
    warnings = lint(doc)
    assert len(warnings) == 1
    assert warnings[0].code == "phase-done-open-tasks"


def test_todo_phase_all_done_warns() -> None:
    doc = _doc(
        phases=[
            Phase(
                slug="ph1",
                name="Phase 1",
                status=PhaseStatus.todo,
                tasks=[Task(text="t", checked=True)],
            )
        ]
    )
    warnings = lint(doc)
    assert len(warnings) == 1
    assert warnings[0].code == "phase-todo-all-tasks-done"


def test_doc_done_with_open_phase_warns() -> None:
    doc = _doc(
        phases=[
            Phase(slug="ph1", name="Phase 1", status=PhaseStatus.doing),
        ],
        status=DocStatus.done,
    )
    warnings = lint(doc)
    assert warnings[0].code == "doc-done-phase-open"


def test_lint_never_raises() -> None:
    assert lint(_doc()) == []
