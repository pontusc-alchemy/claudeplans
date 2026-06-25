"""Pure Document -> Document transforms used by core.py's write path.

Each function returns a NEW Document and never mutates its input: new Documents are
built via ``doc.model_copy(update={...})`` with freshly constructed lists, never an
in-place edit of ``doc.phases``/``doc.sections``. A bad sub-resource reference
(missing phase/anchor, out-of-range index) raises the DOMAIN ValidationError so the
API maps it to 422. Re-validation is implicit: core re-constructs/persists the
Document, so model invariants (unique slugs/anchors, primary∈refs) are enforced on
write rather than re-checked here.

ValidationError here is the domain error, distinct from pydantic.ValidationError.
"""

from pydantic import JsonValue

from claudeplans_contracts import (
    Document,
    Phase,
    Section,
    Task,
    ValidationError,
)
from claudeplans_contracts.enums import DocStatus, PhaseStatus


def _find_phase(doc: Document, slug: str) -> int:
    """Index of the phase with `slug`, or raise a domain ValidationError."""
    for i, phase in enumerate(doc.phases):
        if phase.slug == slug:
            return i
    raise ValidationError(f"no phase {slug!r}")


def _find_section(doc: Document, anchor: str) -> int:
    """Index of the section with `anchor`, or raise a domain ValidationError."""
    for i, section in enumerate(doc.sections):
        if section.anchor == anchor:
            return i
    raise ValidationError(f"no section {anchor!r}")


def _check_task_index(phase: Phase, task_index: int) -> None:
    """Raise a domain ValidationError if `task_index` is out of range for `phase`."""
    if not 0 <= task_index < len(phase.tasks):
        raise ValidationError(
            f"task index {task_index} out of range for phase {phase.slug!r}"
        )


def _merge_patch(
    target: dict[str, JsonValue], patch: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """Apply an RFC 7386 JSON Merge Patch: null deletes, dict merges, else replaces."""
    result = dict(target)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            # Bind the existing value to a local so ty narrows it for the recursive
            # call; re-indexing result[key] inside the branch would not narrow.
            existing = result.get(key)
            if isinstance(existing, dict):
                result[key] = _merge_patch(existing, value)
            else:
                result[key] = _merge_patch({}, value)
        else:
            result[key] = value
    return result


def set_document_status(doc: Document, status: DocStatus) -> Document:
    """Set the document's status."""
    return doc.model_copy(update={"status": status})


def add_phase(doc: Document, slug: str, name: str, status: PhaseStatus) -> Document:
    """Append a phase (the plan surface is append-only; reposition is move_phase).

    Pre-checks slug uniqueness for a clean domain error; the Document validator would
    otherwise surface it as a pydantic ValidationError on re-validate.
    """
    if any(p.slug == slug for p in doc.phases):
        raise ValidationError(f"phase {slug!r} already exists")
    phase = Phase(slug=slug, name=name, status=status)
    return doc.model_copy(update={"phases": [*doc.phases, phase]})


def set_phase(doc: Document, slug: str, name: str | None) -> Document:
    """Absolute set of the provided phase fields; None leaves a field unchanged."""
    i = _find_phase(doc, slug)
    update: dict[str, JsonValue] = {}
    if name is not None:
        update["name"] = name
    phases = list(doc.phases)
    phases[i] = phases[i].model_copy(update=update)
    return doc.model_copy(update={"phases": phases})


def set_phase_status(doc: Document, slug: str, status: PhaseStatus) -> Document:
    """Set the status of the phase identified by `slug`."""
    i = _find_phase(doc, slug)
    phases = list(doc.phases)
    phases[i] = phases[i].model_copy(update={"status": status})
    return doc.model_copy(update={"phases": phases})


def move_phase(doc: Document, slug: str, to_index: int) -> Document:
    """Move the phase `slug` to `to_index` in the ordering."""
    i = _find_phase(doc, slug)
    phases = list(doc.phases)
    phase = phases.pop(i)
    # After removal the valid insert range is [0, len(phases)]; reject anything else
    # so a bad target surfaces as a 422 rather than silently clamping.
    if not 0 <= to_index <= len(phases):
        raise ValidationError(f"to_index {to_index} out of range")
    phases.insert(to_index, phase)
    return doc.model_copy(update={"phases": phases})


def remove_phase(doc: Document, slug: str) -> Document:
    """Remove the phase `slug` (ValidationError if absent — never a silent no-op)."""
    i = _find_phase(doc, slug)
    phases = list(doc.phases)
    del phases[i]
    return doc.model_copy(update={"phases": phases})


def add_task(
    doc: Document, phase_slug: str, text: str, at: int | None = None
) -> Document:
    """Append a task to phase `phase_slug`, or insert at `at` if given."""
    i = _find_phase(doc, phase_slug)
    tasks = list(doc.phases[i].tasks)
    if at is None:
        tasks.append(Task(text=text))
    else:
        if not 0 <= at <= len(tasks):
            raise ValidationError(f"at {at} out of range")
        tasks.insert(at, Task(text=text))
    phases = list(doc.phases)
    phases[i] = phases[i].model_copy(update={"tasks": tasks})
    return doc.model_copy(update={"phases": phases})


def toggle_task(
    doc: Document, phase_slug: str, task_index: int, checked: bool
) -> Document:
    """Set a task's `checked` to the absolute value `checked`."""
    i = _find_phase(doc, phase_slug)
    _check_task_index(doc.phases[i], task_index)
    tasks = list(doc.phases[i].tasks)
    tasks[task_index] = tasks[task_index].model_copy(update={"checked": checked})
    phases = list(doc.phases)
    phases[i] = phases[i].model_copy(update={"tasks": tasks})
    return doc.model_copy(update={"phases": phases})


def edit_task(doc: Document, phase_slug: str, task_index: int, text: str) -> Document:
    """Replace a task's `text`."""
    i = _find_phase(doc, phase_slug)
    _check_task_index(doc.phases[i], task_index)
    tasks = list(doc.phases[i].tasks)
    tasks[task_index] = tasks[task_index].model_copy(update={"text": text})
    phases = list(doc.phases)
    phases[i] = phases[i].model_copy(update={"tasks": tasks})
    return doc.model_copy(update={"phases": phases})


def remove_task(doc: Document, phase_slug: str, task_index: int) -> Document:
    """Remove a task from phase `phase_slug` by index."""
    i = _find_phase(doc, phase_slug)
    _check_task_index(doc.phases[i], task_index)
    tasks = list(doc.phases[i].tasks)
    del tasks[task_index]
    phases = list(doc.phases)
    phases[i] = phases[i].model_copy(update={"tasks": tasks})
    return doc.model_copy(update={"phases": phases})


def move_section(doc: Document, anchor: str, to_index: int) -> Document:
    """Move the section `anchor` to `to_index` in the ordering."""
    i = _find_section(doc, anchor)
    sections = list(doc.sections)
    section = sections.pop(i)
    # After removal the valid insert range is [0, len(sections)]; reject anything else
    # so a bad target surfaces as a 422 rather than silently clamping.
    if not 0 <= to_index <= len(sections):
        raise ValidationError(f"to_index {to_index} out of range")
    sections.insert(to_index, section)
    return doc.model_copy(update={"sections": sections})


def add_section(
    doc: Document,
    anchor: str,
    heading: str,
    body: str,
    level: int,
    at: int | None = None,
) -> Document:
    """Append a section, or insert at `at` if given.

    Pre-checks anchor uniqueness for a clean domain error, mirroring add_phase.
    """
    if any(s.anchor == anchor for s in doc.sections):
        raise ValidationError(f"section {anchor!r} already exists")
    section = Section(anchor=anchor, heading=heading, body=body, level=level)
    sections = list(doc.sections)
    if at is None:
        sections.append(section)
    else:
        if not 0 <= at <= len(sections):
            raise ValidationError(f"at {at} out of range")
        sections.insert(at, section)
    return doc.model_copy(update={"sections": sections})


def set_section(
    doc: Document,
    anchor: str,
    heading: str | None,
    body: str | None,
    level: int | None,
) -> Document:
    """Absolute set of the provided section fields; None leaves a field unchanged."""
    i = _find_section(doc, anchor)
    update: dict[str, JsonValue] = {}
    if heading is not None:
        update["heading"] = heading
    if body is not None:
        update["body"] = body
    if level is not None:
        update["level"] = level
    sections = list(doc.sections)
    sections[i] = sections[i].model_copy(update=update)
    return doc.model_copy(update={"sections": sections})


def patch_section(doc: Document, anchor: str, patch: dict[str, JsonValue]) -> Document:
    """Apply an RFC 7386 JSON Merge Patch to the section, then re-validate it."""
    i = _find_section(doc, anchor)
    merged = _merge_patch(doc.sections[i].model_dump(), patch)
    sections = list(doc.sections)
    # model_validate re-asserts Section's schema, so a patch that nulls a required
    # field or sets a bad type rejects as a pydantic ValidationError (-> 422).
    sections[i] = Section.model_validate(merged)
    return doc.model_copy(update={"sections": sections})


def remove_section(doc: Document, anchor: str) -> Document:
    """Remove the section `anchor` (ValidationError if absent)."""
    i = _find_section(doc, anchor)
    sections = list(doc.sections)
    del sections[i]
    return doc.model_copy(update={"sections": sections})


def put_research_refs(
    doc: Document, research_refs: list[str], primary: str | None
) -> Document:
    """Replace the research refs and primary designation.

    The Document validator enforces primary∈refs and dedup on re-validate.
    """
    return doc.model_copy(
        update={"research_refs": research_refs, "primary_research_ref": primary}
    )


def set_document_meta(
    doc: Document,
    *,
    title: str | None,
    description: str | None,
    date: str | None,
    frontmatter: dict[str, JsonValue] | None,
) -> Document:
    """Absolute set of provided document metadata fields; None leaves unchanged."""
    update: dict[str, JsonValue] = {}
    if title is not None:
        update["title"] = title
    if description is not None:
        update["description"] = description
    if date is not None:
        update["date"] = date
    if frontmatter is not None:
        update["frontmatter"] = frontmatter
    return doc.model_copy(update=update)
