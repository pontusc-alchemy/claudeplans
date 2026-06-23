"""`claudeplans task <verb>` — task-level commands.

Every task mutation except `add` is conditional (--rev): tasks are addressed by
positional index, so the service gates index-based writes with If-Match to catch a
concurrent reorder. Typer descriptors are module-level singletons to satisfy B008.
"""

from typing import Annotated

import typer

from ..context import AppContext
from ..errors import handle_errors
from ..output import emit

app = typer.Typer(no_args_is_help=True)

_TEXT = typer.Argument()
_TASK_INDEX = typer.Argument()
_REV = typer.Option("--rev")
_CHECKED = typer.Option("--checked/--unchecked")


@app.command()
@handle_errors
def add(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    text: Annotated[str, _TEXT],
) -> None:
    """Append a task to a phase."""
    c: AppContext = ctx.obj
    reply = c.client.add_task(c.uid, project, slug, phase_slug, text)
    emit(reply)


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
    """Check or uncheck a task (conditional on --rev)."""
    c: AppContext = ctx.obj
    reply = c.client.toggle_task(
        c.uid, project, slug, phase_slug, task_index, checked, rev=rev
    )
    emit(reply)


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
    emit(reply)


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
    emit(reply)
