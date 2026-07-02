"""`claudeplans schema` — flat command that dumps a stable machine-readable schema.

Derives all values dynamically from the contracts enums, error tables, and the
live Typer/click command tree so it never drifts from the actual vocabulary. No
network request needed.
Typer descriptors are module-level singletons to satisfy ruff B008.
"""

import typer

from claudeplans_contracts import (
    DocStatus,
    DocType,
    ExitCode,
    PhaseStatus,
    SectionPlacement,
)

from ..errors import _ERROR_TO_KIND
from ..output import emit_obj

# Typer auto-adds these to the root callback; they are boilerplate, not part of
# the service contract, so they are excluded from the advertised global flags.
_ROOT_SKIP = frozenset({"install_completion", "show_completion"})


def _has_rev(cmd: object) -> bool:
    """Return True if `cmd` has a REQUIRED --rev option among its params.

    An optional --rev (e.g. `task set-checked`, where --rev is needed only for the
    explicit-index path, not `--all`) does NOT make the command unconditionally
    rev-gated, so it stays out of conditional_writes; that flag's `required:false`
    entry in command_flags conveys the path-dependent requirement instead.
    """
    return any(
        "--rev" in getattr(p, "opts", []) and getattr(p, "required", False)
        for p in getattr(cmd, "params", [])
    )


def _flags(
    cmd: object, *, skip_names: frozenset[str] = frozenset()
) -> list[dict[str, object]]:
    """Describe a command's parameters as flag descriptors for the schema.

    Each entry: {opts, kind: "argument"|"option", required, type}, plus
    secondary_opts when the param has a secondary form (e.g. --checked/--unchecked).
    `type` is the click value type ("text"/"integer"/"boolean"/"choice"), so an
    agent knows --at takes an int and --checked is a no-value boolean toggle. Params
    named in skip_names, or carrying no opts (the Typer-injected context), are
    skipped.
    """
    out: list[dict[str, object]] = []
    for p in getattr(cmd, "params", []):
        if getattr(p, "name", None) in skip_names:
            continue
        opts = list(getattr(p, "opts", []) or [])
        if not opts:
            continue
        entry: dict[str, object] = {
            "opts": opts,
            "kind": getattr(p, "param_type_name", "option"),
            "required": bool(getattr(p, "required", False)),
            "type": getattr(getattr(p, "type", None), "name", None),
        }
        secondary = list(getattr(p, "secondary_opts", []) or [])
        if secondary:
            entry["secondary_opts"] = secondary
        out.append(entry)
    return out


def schema(ctx: typer.Context) -> None:
    """Print a machine-readable JSON schema for the claudeplans CLI contract."""
    root_cmd = ctx.find_root().command
    tree: dict[str, list[str]] = {}
    top: list[str] = []
    conditional: list[str] = []
    command_flags: dict[str, list[dict[str, object]]] = {}
    for name, cmd in sorted(root_cmd.commands.items()):  # ty: ignore[unresolved-attribute]
        subcmds = getattr(cmd, "commands", None)
        if subcmds:  # group
            tree[name] = sorted(subcmds.keys())
            for sub, leaf in sorted(subcmds.items()):
                if _has_rev(leaf):
                    conditional.append(f"{name} {sub}")
                command_flags[f"{name} {sub}"] = _flags(leaf)
        else:
            top.append(name)
            if _has_rev(cmd):
                conditional.append(name)
            command_flags[name] = _flags(cmd)
    if top:
        tree["top"] = sorted(top)
    # Root global flags (--url/--uid/--full) are passed before the subcommand, so
    # they live in their own key rather than under any per-command entry.
    global_flags = _flags(root_cmd, skip_names=_ROOT_SKIP)

    emit_obj(
        {
            "enums": {
                "doc_status": [s.value for s in DocStatus],
                "doc_type": [t.value for t in DocType],
                "phase_status": [p.value for p in PhaseStatus],
                "section_placement": [p.value for p in SectionPlacement],
            },
            "env": {
                "NO_COLOR": "set (any value) for ANSI-free --help / usage output",
            },
            "exit_codes": {c.name.lower(): int(c) for c in ExitCode},
            "error_kinds": sorted({*_ERROR_TO_KIND.values(), "transport", "error"}),
            "envelopes": {
                "read": "{rev, data, warnings}",
                "read_phases": "{rev, phases, warnings}",
                "read_rev": (
                    "bare rev token by default; {rev} envelope behind --json/--full"
                ),
                "write_default": "{rev, warnings}",
                "write_create": "{slug, type, rev, warnings}",
                "write_task_add": (
                    "{rev, warnings, task:{phase, index, text, checked}}"
                ),
                "write_phase_slice": "{rev, warnings, phase:{slug, status, tasks}}",
                "write_phases_ordering": "{rev, warnings, phases:[{slug,status}]}",
                "list": "{data, warnings}  (data: items-list|lineage-tree|search-hits)",
                "view": "{url}",
                "doctor": (
                    "{url, uid, reachable, version?, storage_backend?, "
                    "auth_mode?, detail?}"
                ),
                "error_stderr": ("{error, detail}  (stale_rev: {error, current_rev})"),
                "full_flag": (
                    "--full/-v restores {rev, data, warnings} on writes; "
                    "also switches `doc rev` to the {rev} envelope"
                ),
            },
            "commands": tree,
            "command_flags": dict(sorted(command_flags.items())),
            "global_flags": global_flags,
            "global_flags_usage": (
                "global_flags are passed before the subcommand: "
                "claudeplans <global_flags> <command> [args/command_flags]"
            ),
            "move_index": (
                "phase/section move to_index is the absolute position AFTER the "
                "item is removed from its current slot: valid range [0, count-1]"
            ),
            "conditional_writes": sorted(conditional),
        }
    )
