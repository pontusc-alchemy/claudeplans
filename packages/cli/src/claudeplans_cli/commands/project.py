"""`claudeplans project <verb>` — project-level commands.

`project list` queries the server for all projects under the caller's uid.
`project view` prints the lineage URL for a project without making a request.

Typer descriptors are module-level singletons to satisfy ruff B008.
"""

import typer

from ..context import AppContext
from ..errors import handle_errors
from ..output import emit_obj

app = typer.Typer(no_args_is_help=True)


@app.callback()
def _callback() -> None:
    """Project-level commands."""


@app.command("list")
@handle_errors
def list_(ctx: typer.Context) -> None:
    """List all projects for the configured user."""
    c: AppContext = ctx.obj
    emit_obj({"data": c.client.list_projects(c.uid), "warnings": []})


@app.command()
@handle_errors
def view(ctx: typer.Context, project: str) -> None:
    """Print the API URL for a project (no network request)."""
    c: AppContext = ctx.obj
    base = c.base_url.rstrip("/")
    emit_obj({"url": f"{base}/v1/users/{c.uid}/projects/{project}/"})


@app.command()
@handle_errors
def lineage(ctx: typer.Context, project: str) -> None:
    """Return the lineage tree for a project as JSON."""
    c: AppContext = ctx.obj
    emit_obj({"data": c.client.lineage(c.uid, project), "warnings": []})
