"""`claudeplans section <verb>` — section-level commands.

`set` does an absolute field set (omit a flag to leave it unchanged); `patch` sends
a JSON merge-patch. Both are stable-key (anchor-addressed) so no --rev is needed.
The set function is named `set_section` to avoid shadowing the builtin and registered
as "set". Typer descriptors are module-level singletons to satisfy B008.
"""

import json
from typing import Annotated

import typer

from claudeplans_contracts import ValidationError

from ..context import AppContext
from ..errors import handle_errors
from ..output import emit_write

app = typer.Typer(no_args_is_help=True)

_ADD_HEADING = typer.Argument()
_ADD_BODY = typer.Option("--body")
_ADD_LEVEL = typer.Option("--level")
_SET_HEADING = typer.Option()
_SET_BODY = typer.Option()
_SET_LEVEL = typer.Option()
_MERGE_PATCH = typer.Option("--merge-patch", help="JSON object")


@app.command()
@handle_errors
def add(
    ctx: typer.Context,
    project: str,
    slug: str,
    anchor: str,
    heading: Annotated[str, _ADD_HEADING],
    body: Annotated[str, _ADD_BODY] = "",
    level: Annotated[int, _ADD_LEVEL] = 2,
) -> None:
    """Append a section."""
    c: AppContext = ctx.obj
    reply = c.client.add_section(c.uid, project, slug, anchor, heading, body, level)
    emit_write(reply, full=c.full)


@app.command("set")
@handle_errors
def set_section(
    ctx: typer.Context,
    project: str,
    slug: str,
    anchor: str,
    heading: Annotated[str | None, _SET_HEADING] = None,
    body: Annotated[str | None, _SET_BODY] = None,
    level: Annotated[int | None, _SET_LEVEL] = None,
) -> None:
    """Absolute-set a section's fields (omitted flags are left unchanged)."""
    c: AppContext = ctx.obj
    reply = c.client.set_section(c.uid, project, slug, anchor, heading, body, level)
    emit_write(reply, full=c.full)


@app.command()
@handle_errors
def patch(
    ctx: typer.Context,
    project: str,
    slug: str,
    anchor: str,
    merge_patch: Annotated[str, _MERGE_PATCH],
) -> None:
    """Apply a JSON merge-patch to a section."""
    c: AppContext = ctx.obj
    # Parse inside the handle_errors boundary: a malformed --merge-patch is a client
    # error (-> exit 4), not an uncaught JSONDecodeError that escapes as exit 1.
    try:
        patch_obj = json.loads(merge_patch)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"--merge-patch is not valid JSON: {exc}") from exc
    reply = c.client.patch_section(c.uid, project, slug, anchor, patch_obj)
    emit_write(reply, full=c.full)


@app.command()
@handle_errors
def rm(ctx: typer.Context, project: str, slug: str, anchor: str) -> None:
    """Remove a section."""
    c: AppContext = ctx.obj
    reply = c.client.remove_section(c.uid, project, slug, anchor)
    emit_write(reply, full=c.full)
