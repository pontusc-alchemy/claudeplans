"""`claudeplans schema` — flat command that dumps a stable machine-readable schema.

Derives all values dynamically from the contracts enums, error tables, and the
live Typer/click command tree so it never drifts from the actual vocabulary. No
network request needed.
Typer descriptors are module-level singletons to satisfy ruff B008.
"""

import typer

from claudeplans_contracts import DocStatus, DocType, ExitCode, PhaseStatus

from ..errors import _ERROR_TO_KIND
from ..output import emit_obj


def _has_rev(cmd: object) -> bool:
    """Return True if `cmd` has a --rev option among its params."""
    return any("--rev" in getattr(p, "opts", []) for p in getattr(cmd, "params", []))


def schema(ctx: typer.Context) -> None:
    """Print a machine-readable JSON schema for the claudeplans CLI contract."""
    root_cmd = ctx.find_root().command
    tree: dict[str, list[str]] = {}
    top: list[str] = []
    conditional: list[str] = []
    for name, cmd in sorted(root_cmd.commands.items()):  # ty: ignore[unresolved-attribute]
        subcmds = getattr(cmd, "commands", None)
        if subcmds:  # group
            tree[name] = sorted(subcmds.keys())
            for sub, leaf in subcmds.items():
                if _has_rev(leaf):
                    conditional.append(f"{name} {sub}")
        else:
            top.append(name)
            if _has_rev(cmd):
                conditional.append(name)
    if top:
        tree["top"] = sorted(top)

    emit_obj(
        {
            "enums": {
                "doc_status": [s.value for s in DocStatus],
                "doc_type": [t.value for t in DocType],
                "phase_status": [p.value for p in PhaseStatus],
            },
            "env": {
                "NO_COLOR": "set (any value) for ANSI-free --help / usage output",
            },
            "exit_codes": {c.name.lower(): int(c) for c in ExitCode},
            "error_kinds": sorted({*_ERROR_TO_KIND.values(), "transport", "error"}),
            "envelopes": {
                "read": "{rev, data, warnings}",
                "read_phases": "{rev, phases, warnings}",
                "read_rev": "{rev}",
                "write_default": "{rev, warnings}",
                "write_create": "{slug, type, rev, warnings}",
                "write_phase_slice": "{rev, warnings, phase:{slug, tasks}}",
                "write_phases_ordering": "{rev, warnings, phases:[{slug,status}]}",
                "list": "{data, warnings}  (data: items-list|lineage-tree|search-hits)",
                "view": "{url}",
                "error_stderr": ("{error, detail}  (stale_rev: {error, current_rev})"),
                "full_flag": "--full/-v restores {rev, data, warnings} on writes",
            },
            "commands": tree,
            "conditional_writes": sorted(conditional),
        }
    )
