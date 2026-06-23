"""Compact-JSON rendering of read/write replies for agent consumption.

WHY compact, single-line JSON: the CLI's consumer is an LLM agent piping stdout
through `json.loads`, not a human reading a table. One line per reply keeps parsing
trivial and output diffable. HTML is never emitted — the wire contract is JSON only.
The projection options (fields/section/phase) let a caller fetch the whole document
once and narrow the printed view without a second round-trip.
"""

import json

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
    """Print a reply as compact JSON, optionally projecting the document.

    fields/section/phase are mutually exclusive; the command layer passes at most
    one. With none, the full `{"rev", "data", "warnings"}` envelope is printed.
    """
    data = reply.data
    if fields is not None and data is not None:
        projected: object = {k: data[k] for k in fields if k in data}
    elif section is not None and data is not None:
        projected = next(
            (s for s in data.get("sections", []) if s.get("anchor") == section),
            None,
        )
    elif phase is not None and data is not None:
        projected = next(
            (p for p in data.get("phases", []) if p.get("slug") == phase),
            None,
        )
    else:
        _compact({"rev": reply.rev, "data": data, "warnings": reply.warnings})
        return
    _compact({"rev": reply.rev, "data": projected, "warnings": reply.warnings})


def emit_phases(reply: Reply) -> None:
    """Print just the document's phases list (plus rev) as compact JSON."""
    phases = reply.data.get("phases", []) if reply.data is not None else []
    _compact({"rev": reply.rev, "phases": phases})
