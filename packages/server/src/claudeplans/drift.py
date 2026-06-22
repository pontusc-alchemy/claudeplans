"""The drift linter — NON-RAISING. Structural errors are handled elsewhere.

Structural problems reject at the boundary (pydantic -> HTTP 422). Drift is the
softer class: valid-but-off (stale anchors, legacy markers, status/state
mismatches). This returns warnings and the write still proceeds; the API folds
them into the single {data, warnings[]} envelope. Built out in the data-model
phase; this module marks the seam.
"""

from claudeplans_contracts import DocStatus, Document, DriftWarning, PhaseStatus


def lint(doc: Document) -> list[DriftWarning]:
    """Return drift warnings for a document; never raises.

    Under the structured model, drift is a status/state mismatch rather than a stale
    markdown anchor: anchors and task markers are now generated, not authored, so the
    only thing that can fall out of sync is whether a declared status matches the
    underlying task/phase state.
    """
    warnings: list[DriftWarning] = []
    for phase in doc.phases:
        if phase.status is PhaseStatus.done and any(not t.checked for t in phase.tasks):
            warnings.append(
                DriftWarning(
                    code="phase-done-open-tasks",
                    message=f"phase '{phase.slug}' is done but has unchecked tasks",
                    path=f"phases.{phase.slug}",
                )
            )
        if (
            phase.status is PhaseStatus.todo
            and phase.tasks
            and all(t.checked for t in phase.tasks)
        ):
            warnings.append(
                DriftWarning(
                    code="phase-todo-all-tasks-done",
                    message=f"phase '{phase.slug}' is todo but all tasks are checked",
                    path=f"phases.{phase.slug}",
                )
            )
        if doc.status is DocStatus.done and phase.status is not PhaseStatus.done:
            warnings.append(
                DriftWarning(
                    code="doc-done-phase-open",
                    message=f"document is done but phase '{phase.slug}' is not done",
                    path=f"phases.{phase.slug}",
                )
            )
    return warnings
