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

app = typer.Typer(no_args_is_help=True)

_NAME = typer.Argument()
_ADD_STATUS = typer.Option()
_STATUS = typer.Argument()
_TO_INDEX = typer.Argument()
_REV = typer.Option("--rev")


@app.command()
@handle_errors
def add(
    ctx: typer.Context,
    project: str,
    slug: str,
    phase_slug: str,
    name: Annotated[str, _NAME],
    status: Annotated[PhaseStatus, _ADD_STATUS] = PhaseStatus.todo,
) -> None:
    """Append a phase."""
    c: AppContext = ctx.obj
    reply = c.client.add_phase(c.uid, project, slug, phase_slug, name, status.value)
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
    """Move a phase to a new index (conditional on --rev)."""
    c: AppContext = ctx.obj
    reply = c.client.move_phase(c.uid, project, slug, phase_slug, to_index, rev=rev)
    emit_write(reply, full=c.full, slice_="phases-ordering")


@app.command()
@handle_errors
def rm(ctx: typer.Context, project: str, slug: str, phase_slug: str) -> None:
    """Remove a phase."""
    c: AppContext = ctx.obj
    reply = c.client.remove_phase(c.uid, project, slug, phase_slug)
    emit_write(reply, full=c.full)
