"""`claudeplans task <verb>` — task-level commands.

Every task mutation except `add` is conditional (--rev): tasks are addressed by
positional index, so the service gates index-based writes with If-Match to catch a
concurrent reorder. Typer descriptors are module-level singletons to satisfy B008.
"""

from typing import Annotated

import typer

from ..context import AppContext
from ..errors import handle_errors
from ..output import emit_task_added, emit_write

app = typer.Typer(no_args_is_help=True)

_TEXT = typer.Argument()
_TASK_INDEX = typer.Argument()
_REV = typer.Option(
    "--rev",
    help="current rev; this write is position-sensitive (see 'doc rev')",
)
_CHECKED = typer.Option("--checked/--unchecked")
_CHECKED_ARG = typer.Argument()
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
    text: Annotated[str, _TEXT],
    at: Annotated[int | None, _AT] = None,
    checked: Annotated[bool, _CHECKED] = False,
) -> None:
    """Append a task to a phase, or insert at --at if given.

    Use --checked/--unchecked to set the initial state; defaults to unchecked.
    """
    c: AppContext = ctx.obj
    reply = c.client.add_task(c.uid, project, slug, phase_slug, text, at, checked)
    data = reply.data or {}
    phase = next(
        (p for p in data.get("phases", []) if p.get("slug") == phase_slug), None
    )
    tasks = phase.get("tasks", []) if phase else []
    index = at if at is not None else len(tasks) - 1
    emit_task_added(reply, phase_slug=phase_slug, index=index, full=c.full)


@app.command()
@handle_errors
def toggle(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    task_index: Annotated[int, _TASK_INDEX],
    rev: Annotated[str, _REV],
    checked: Annotated[bool, _CHECKED] = True,
) -> None:
    """Set a task checked/unchecked via --checked/--unchecked (conditional on --rev).

    Despite the name this is an absolute set, not a flip — identical effect to
    `set-checked`, which takes a positional <true|false> instead of the flag.
    """
    c: AppContext = ctx.obj
    reply = c.client.toggle_task(
        c.uid, project, slug, phase_slug, task_index, checked, rev=rev
    )
    emit_write(reply, full=c.full, slice_=f"phase:{phase_slug}")


@app.command("set-checked")
@handle_errors
def set_checked(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    task_index: Annotated[int, _TASK_INDEX],
    checked: Annotated[bool, _CHECKED_ARG],
    rev: Annotated[str, _REV],
) -> None:
    """Set a task's checked state to an absolute <true|false> (conditional on --rev).

    Idempotent (asserting a known state needs no prior read). Same effect and endpoint
    as `toggle`, which spells the boolean as --checked/--unchecked instead.
    """
    c: AppContext = ctx.obj
    reply = c.client.toggle_task(
        c.uid, project, slug, phase_slug, task_index, checked, rev=rev
    )
    emit_write(reply, full=c.full, slice_=f"phase:{phase_slug}")


@app.command()
@handle_errors
def edit(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    task_index: Annotated[int, _TASK_INDEX],
    text: Annotated[str, _TEXT],
    rev: Annotated[str, _REV],
) -> None:
    """Replace a task's text (conditional on --rev)."""
    c: AppContext = ctx.obj
    reply = c.client.edit_task(
        c.uid, project, slug, phase_slug, task_index, text, rev=rev
    )
    emit_write(reply, full=c.full, slice_=f"phase:{phase_slug}")


@app.command()
@handle_errors
def rm(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    task_index: Annotated[int, _TASK_INDEX],
    rev: Annotated[str, _REV],
) -> None:
    """Remove a task (conditional on --rev)."""
    c: AppContext = ctx.obj
    reply = c.client.remove_task(c.uid, project, slug, phase_slug, task_index, rev=rev)
    emit_write(reply, full=c.full, slice_=f"phase:{phase_slug}")
