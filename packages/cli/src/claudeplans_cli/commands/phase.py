"""`claudeplans phase <verb>` — phase-level commands.

`move` is conditional (--rev) because reordering is a structural write the service
gates with If-Match; the other phase mutations are stable-key and retry-safe.
Typer descriptors are module-level singletons to satisfy ruff B008.
"""

from typing import Annotated

import typer

from claudeplans_contracts import PhaseStatus

from ..context import AppContext
from ..errors import handle_errors
from ..output import emit_write
from ..prose import resolve_prose

app = typer.Typer(no_args_is_help=True)

_NAME = typer.Argument()
_ADD_STATUS = typer.Option(help="phase lifecycle status; defaults to todo")
_STATUS = typer.Argument()
_TO_INDEX = typer.Argument()
_REV = typer.Option(
    "--rev",
    help="current rev; this write is position-sensitive (see 'doc rev')",
)
_SET_NAME = typer.Option("--name")
_SET_INTRO = typer.Option(
    "--intro", help="phase intro prose; '' clears, omit to leave unchanged"
)
_SET_EXIT = typer.Option(
    "--exit-criteria", help="exit-criteria prose; '' clears, omit to leave unchanged"
)
_SET_NOTES = typer.Option(
    "--notes", help="phase notes/revision prose; '' clears, omit to leave unchanged"
)
_SET_INTRO_FILE = typer.Option(
    "--intro-file", help="read --intro from a file ('-' = stdin); excludes --intro"
)
_SET_EXIT_FILE = typer.Option(
    "--exit-criteria-file",
    help="read --exit-criteria from a file ('-' = stdin); excludes --exit-criteria",
)
_SET_NOTES_FILE = typer.Option(
    "--notes-file", help="read --notes from a file ('-' = stdin); excludes --notes"
)
# `add` is a create, so its omit-semantics differ from `set` (no prior value to
# leave unchanged): omitted prose defaults to empty. Distinct help avoids the
# misleading "'' clears, omit to leave unchanged" wording on `phase add --help`.
# The --*-file variants reuse the _SET_*_FILE singletons (their help is neutral).
_ADD_INTRO = typer.Option(
    "--intro", help="phase intro prose (markdown); omitted = empty"
)
_ADD_EXIT = typer.Option(
    "--exit-criteria", help="exit-criteria prose (markdown); omitted = empty"
)
_ADD_NOTES = typer.Option(
    "--notes", help="phase notes prose (markdown); omitted = empty"
)
_AT = typer.Option(
    "--at",
    help="0-based insert position; appends if omitted. Unconditional (no --rev).",
)


@app.command()
@handle_errors
def add(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    name: Annotated[str, _NAME],
    status: Annotated[PhaseStatus, _ADD_STATUS] = PhaseStatus.todo,
    at: Annotated[int | None, _AT] = None,
    intro: Annotated[str | None, _ADD_INTRO] = None,
    exit_criteria: Annotated[str | None, _ADD_EXIT] = None,
    notes: Annotated[str | None, _ADD_NOTES] = None,
    intro_file: Annotated[str | None, _SET_INTRO_FILE] = None,
    exit_criteria_file: Annotated[str | None, _SET_EXIT_FILE] = None,
    notes_file: Annotated[str | None, _SET_NOTES_FILE] = None,
) -> None:
    """Append a phase (or insert at --at), optionally with prose, in one call.

    Prose flags accept inline text or a --<flag>-file path ('-' = stdin);
    omitted prose defaults to empty.
    """
    c: AppContext = ctx.obj
    intro = resolve_prose(intro, intro_file, "intro") or ""
    exit_criteria = (
        resolve_prose(exit_criteria, exit_criteria_file, "exit-criteria") or ""
    )
    notes = resolve_prose(notes, notes_file, "notes") or ""
    reply = c.client.add_phase(
        c.uid,
        project,
        slug,
        phase_slug,
        name,
        status.value,
        intro,
        exit_criteria,
        notes,
        at,
    )
    emit_write(reply, full=c.full)


@app.command("set")
@handle_errors
def set_phase(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    name: Annotated[str | None, _SET_NAME] = None,
    intro: Annotated[str | None, _SET_INTRO] = None,
    exit_criteria: Annotated[str | None, _SET_EXIT] = None,
    notes: Annotated[str | None, _SET_NOTES] = None,
    intro_file: Annotated[str | None, _SET_INTRO_FILE] = None,
    exit_criteria_file: Annotated[str | None, _SET_EXIT_FILE] = None,
    notes_file: Annotated[str | None, _SET_NOTES_FILE] = None,
) -> None:
    """Absolute-set a phase's fields (omitted flags are left unchanged).

    Prose flags accept inline text or a --<flag>-file path ('-' = stdin) for
    multi-line markdown without shell-quoting pain.
    """
    c: AppContext = ctx.obj
    intro = resolve_prose(intro, intro_file, "intro")
    exit_criteria = resolve_prose(exit_criteria, exit_criteria_file, "exit-criteria")
    notes = resolve_prose(notes, notes_file, "notes")
    reply = c.client.set_phase(
        c.uid, project, slug, phase_slug, name, intro, exit_criteria, notes
    )
    emit_write(reply, full=c.full)


@app.command("set-status")
@handle_errors
def set_status(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    status: Annotated[PhaseStatus, _STATUS],
) -> None:
    """Set a phase's status."""
    c: AppContext = ctx.obj
    reply = c.client.set_phase_status(c.uid, project, slug, phase_slug, status.value)
    emit_write(reply, full=c.full)


@app.command()
@handle_errors
def move(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    to_index: Annotated[int, _TO_INDEX],
    rev: Annotated[str, _REV],
) -> None:
    """Move a phase to a new index (conditional on --rev).

    to_index is the absolute position AFTER the phase is removed from its current
    slot, so the valid range is [0, phase_count - 1].
    """
    c: AppContext = ctx.obj
    reply = c.client.move_phase(c.uid, project, slug, phase_slug, to_index, rev=rev)
    emit_write(reply, full=c.full, slice_="phases-ordering")


@app.command()
@handle_errors
def complete(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
) -> None:
    """Check every task in the phase and mark it done, in one rev-free call.

    A whole-phase transition: tasks are checked before the status flip, so it never
    trips the done-with-open-tasks warning. Convenience over `task set-checked --all`
    then `phase set-status done`.
    """
    c: AppContext = ctx.obj
    reply = c.client.complete_phase(c.uid, project, slug, phase_slug)
    emit_write(reply, full=c.full, slice_=f"phase:{phase_slug}")


@app.command()
@handle_errors
def rm(ctx: typer.Context, project: str, slug: str, phase_slug: str) -> None:
    """Remove a phase."""
    c: AppContext = ctx.obj
    reply = c.client.remove_phase(c.uid, project, slug, phase_slug)
    emit_write(reply, full=c.full)
