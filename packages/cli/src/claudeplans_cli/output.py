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
  - "phase:<slug>"    → {rev, warnings, phase:{slug, tasks}}
  - "phases-ordering" → {rev, warnings, phases:[{slug, status}]}
  - None (default)    → {rev, warnings}
task-add shape (emit_task_added, full=False):
  - {rev, warnings, task:{phase:<slug>, index:<int>}}
"""

import json

from claudeplans_contracts import ValidationError

from .client import Reply


def _compact(obj: object) -> None:
    """Print `obj` as single-line JSON to stdout (no spaces, agent-parseable)."""
    print(json.dumps(obj, separators=(",", ":")))


def emit(
    reply: Reply,
    *,
    fields: list[str] | None = None,
    section: str | None = None,
    phase: str | None = None,
) -> None:
    """Print a read reply as compact JSON, optionally projecting the document.

    fields/section/phase are mutually exclusive; the command layer passes at most
    one. With none, the full `{"rev", "data", "warnings"}` envelope is printed.
    This function is for READ paths only; write paths use `emit_write`.
    """
    data = reply.data
    if fields is not None and data is not None:
        missing = [k for k in fields if k not in data]
        if missing:
            raise ValidationError(f"unknown field(s): {', '.join(missing)}")
        projected: object = {k: data[k] for k in fields}
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
      - "phase:<slug>"  → {rev, warnings, phase:{slug, tasks}}
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
        if isinstance(data, dict):
            matched = next(
                (p for p in data.get("phases", []) if p.get("slug") == phase_slug),
                None,
            )
            tasks = matched.get("tasks", []) if isinstance(matched, dict) else []
        _compact(
            {
                "rev": reply.rev,
                "warnings": reply.warnings,
                "phase": {"slug": phase_slug, "tasks": tasks},
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
    reply: Reply, *, phase_slug: str, index: int, full: bool = False
) -> None:
    """Print a task-add reply as compact JSON.

    full=True: full {rev, data, warnings} envelope.
    full=False: {rev, warnings, task:{phase:<slug>, index:<int>}}.
    """
    if full:
        _compact({"rev": reply.rev, "data": reply.data, "warnings": reply.warnings})
        return
    _compact(
        {
            "rev": reply.rev,
            "warnings": reply.warnings,
            "task": {"phase": phase_slug, "index": index},
        }
    )


def emit_phases(reply: Reply) -> None:
    """Print just the document's phases list (plus rev and warnings) as compact JSON."""
    phases = reply.data.get("phases", []) if reply.data is not None else []
    _compact({"rev": reply.rev, "phases": phases, "warnings": reply.warnings})


def emit_obj(obj: object) -> None:
    """Print a plain object as compact single-line JSON to stdout."""
    _compact(obj)
