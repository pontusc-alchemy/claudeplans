"""The claudeplans CLI entrypoint: resource-grouped subcommands over the service.

The root callback resolves the service URL and caller identity once (from flags or
env) and stashes a built PlanClient on Typer's `ctx.obj`. `build_client` is a
module-level seam tests monkeypatch to inject an in-process ASGITransport client,
so the whole command tree can run against the app object without a socket.
Typer descriptors are module-level singletons to satisfy ruff B008.
"""

from typing import Annotated

import typer

from .client import PlanClient
from .commands import doc, phase, section, task
from .context import AppContext

app = typer.Typer(name="claudeplans", no_args_is_help=True)

app.add_typer(doc.app, name="doc")
app.add_typer(phase.app, name="phase")
app.add_typer(task.app, name="task")
app.add_typer(section.app, name="section")

_URL = typer.Option(envvar="CLAUDEPLANS_URL")
_UID = typer.Option(envvar="CLAUDEPLANS_UID")


def build_client(url: str) -> PlanClient:
    """Build the client for a service URL (a seam tests monkeypatch)."""
    return PlanClient(url)


@app.callback()
def _root(
    ctx: typer.Context,
    url: Annotated[str, _URL] = "http://127.0.0.1:8000",
    uid: Annotated[str, _UID] = "dev",
) -> None:
    """Agent client for the claudeplans service."""
    ctx.obj = AppContext(client=build_client(url), uid=uid)


def main() -> None:
    """Console-script entrypoint (see [project.scripts] in pyproject.toml)."""
    app()


if __name__ == "__main__":
    main()
