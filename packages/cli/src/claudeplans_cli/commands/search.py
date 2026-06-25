"""`claudeplans search <project> <query>` — flat search command.

Queries the server's in-memory title/heading/phase index for a project.
Typer descriptors are module-level singletons to satisfy ruff B008.
"""

import typer

from ..context import AppContext
from ..errors import handle_errors
from ..output import emit_obj


@handle_errors
def search(ctx: typer.Context, project: str, query: str) -> None:
    """Search title and heading index within a project."""
    c: AppContext = ctx.obj
    result = c.client.search(c.uid, project, query)
    emit_obj({"data": result, "warnings": []})
