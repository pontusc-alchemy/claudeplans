"""Compact-JSON rendering of read/write replies for agent consumption.

WHY compact, single-line JSON: the CLI's consumer is an LLM agent piping stdout
through `json.loads`, not a human reading a table. One line per reply keeps parsing
trivial and output diffable. HTML is never emitted — the wire contract is JSON only.
The projection options (fields/section/phase) let a caller fetch the whole document
once and narrow the printed view without a second round-trip.

Write replies have a slimmer default shape that omits the full document body.
Pass `full=True` (--full/-v) to restore the full `{rev, data, warnings}` envelope.
Slice directives narrow the output further without a second request:
  - "create"          → {slug, type, rev, warnings}
  - "phase:<slug>"    → {rev, warnings, phase:{slug, status, tasks}}
  - "phases-ordering" → {rev, warnings, phases:[{slug, status}]}
  - None (default)    → {rev, warnings}
task-add shape (emit_task_added, full=False):
  - {rev, warnings, task:{phase:<slug>, index:<int>, text:<str>, checked:<bool>}}
    (text/checked echo the created task so the add is self-verifying)
"""

import json

from claudeplans_contracts import ValidationError

from .client import Reply


def _compact(obj: object) -> None:
    """Print `obj` as single-line JSON to stdout (no spaces, agent-parseable)."""
    print(json.dumps(obj, separators=(",", ":")))


def _outline(data: dict) -> dict[str, object]:
    """Structure without prose: what a document contains, not what it says.

    `placement` rides along because it decides whether a section renders before or
    after the phases — an outline that omits it states the wrong order. Task counts
    replace the task list: how much is left is the question an outline answers.
    """
    sections = [
        {
            "anchor": s.get("anchor"),
            "heading": s.get("heading"),
            "level": s.get("level"),
            "placement": s.get("placement"),
        }
        for s in data.get("sections", [])
    ]
    phases = []
    for p in data.get("phases", []):
        tasks = p.get("tasks", [])
        phases.append(
            {
                "slug": p.get("slug"),
                "name": p.get("name"),
                "status": p.get("status"),
                "tasks": {
                    "total": len(tasks),
                    "checked": sum(1 for t in tasks if t.get("checked")),
                },
            }
        )
    return {
        "slug": data.get("slug"),
        "type": data.get("type"),
        "status": data.get("status"),
        "title": data.get("title"),
        "sections": sections,
        "phases": phases,
        "primary_research_ref": data.get("primary_research_ref"),
        "research_refs": data.get("research_refs", []),
    }


def emit(
    reply: Reply,
    *,
    fields: list[str] | None = None,
    section: str | None = None,
    phase: str | None = None,
    outline: bool = False,
) -> None:
    """Print a read reply as compact JSON, optionally projecting the document.

    fields/section/phase/outline are mutually exclusive; the command layer passes at
    most one. With none, the full `{"rev", "data", "warnings"}` envelope is printed.
    This function is for READ paths only; write paths use `emit_write`.
    """
    data = reply.data
    if outline and data is not None:
        projected: object = _outline(data)
    elif fields is not None and data is not None:
        missing = [k for k in fields if k not in data]
        if missing:
            raise ValidationError(f"unknown field(s): {', '.join(missing)}")
        projected = {k: data[k] for k in fields}
    elif section is not None and data is not None:
        found_section = next(
            (s for s in data.get("sections", []) if s.get("anchor") == section),
            None,
        )
        if found_section is None:
            raise ValidationError(f"no section with anchor {section!r}")
        projected = found_section
    elif phase is not None and data is not None:
        found_phase = next(
            (p for p in data.get("phases", []) if p.get("slug") == phase),
            None,
        )
        if found_phase is None:
            raise ValidationError(f"no phase with slug {phase!r}")
        projected = found_phase
    else:
        _compact({"rev": reply.rev, "data": data, "warnings": reply.warnings})
        return
    _compact({"rev": reply.rev, "data": projected, "warnings": reply.warnings})


def emit_write(
    reply: Reply,
    *,
    full: bool = False,
    slice_: str | None = None,
) -> None:
    """Print a write reply as compact JSON.

    Default (full=False): slim shape; `slice_` controls what is included:
      - None            → {rev, warnings}
      - "create"        → {slug, type, rev, warnings}
      - "phase:<slug>"  → {rev, warnings, phase:{slug, status, tasks}}
      - "phases-ordering" → {rev, warnings, phases:[{slug, status}]}

    full=True: always prints the full {rev, data, warnings} envelope, matching the
    old behaviour (equivalent to passing --full/-v on the CLI).
    """
    if full:
        _compact({"rev": reply.rev, "data": reply.data, "warnings": reply.warnings})
        return

    data = reply.data

    if slice_ == "create":
        slug = data.get("slug") if isinstance(data, dict) else None
        type_ = data.get("type") if isinstance(data, dict) else None
        _compact(
            {"slug": slug, "type": type_, "rev": reply.rev, "warnings": reply.warnings}
        )
        return

    if slice_ is not None and slice_.startswith("phase:"):
        phase_slug = slice_[len("phase:") :]
        tasks: object = None
        status: object = None
        if isinstance(data, dict):
            matched = next(
                (p for p in data.get("phases", []) if p.get("slug") == phase_slug),
                None,
            )
            if isinstance(matched, dict):
                tasks = matched.get("tasks", [])
                status = matched.get("status")
            else:
                tasks = []
        _compact(
            {
                "rev": reply.rev,
                "warnings": reply.warnings,
                "phase": {"slug": phase_slug, "status": status, "tasks": tasks},
            }
        )
        return

    if slice_ == "phases-ordering":
        phases: list[object] = []
        if isinstance(data, dict):
            phases = [
                {"slug": p.get("slug"), "status": p.get("status")}
                for p in data.get("phases", [])
            ]
        _compact({"rev": reply.rev, "warnings": reply.warnings, "phases": phases})
        return

    # Generic mutation default: {rev, warnings}
    _compact({"rev": reply.rev, "warnings": reply.warnings})


def emit_task_added(
    reply: Reply,
    *,
    phase_slug: str,
    index: int,
    text: str | None = None,
    checked: bool | None = None,
    full: bool = False,
) -> None:
    """Print a task-add reply as compact JSON.

    full=True: full {rev, data, warnings} envelope.
    full=False: {rev, warnings, task:{phase:<slug>, index:<int>, text, checked}}.
    Echoing the created task's text/checked makes the add self-verifying — a
    checked-at-creation task needs no follow-up `doc phases` read to confirm.
    text/checked are null when the just-added task can't be located in the reply.
    """
    if full:
        _compact({"rev": reply.rev, "data": reply.data, "warnings": reply.warnings})
        return
    _compact(
        {
            "rev": reply.rev,
            "warnings": reply.warnings,
            "task": {
                "phase": phase_slug,
                "index": index,
                "text": text,
                "checked": checked,
            },
        }
    )


def emit_phases(reply: Reply) -> None:
    """Print just the document's phases list (plus rev and warnings) as compact JSON."""
    phases = reply.data.get("phases", []) if reply.data is not None else []
    _compact({"rev": reply.rev, "phases": phases, "warnings": reply.warnings})


def emit_obj(obj: object) -> None:
    """Print a plain object as compact single-line JSON to stdout."""
    _compact(obj)
