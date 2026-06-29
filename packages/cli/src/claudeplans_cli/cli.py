"""The claudeplans CLI entrypoint: resource-grouped subcommands over the service.

The root callback resolves the service URL and caller identity once (from flags or
env) and stashes a built PlanClient on Typer's `ctx.obj`. `build_client` is a
module-level seam tests monkeypatch to inject an in-process ASGITransport client,
so the whole command tree can run against the app object without a socket.
Typer descriptors are module-level singletons to satisfy ruff B008.
"""

import os
from typing import Annotated

import httpx
import typer
import typer.rich_utils

# Honour the NO_COLOR standard (https://no-color.org): any non-empty value means
# the caller has opted out of ANSI colour. Typer/rich do not check NO_COLOR
# themselves, so we zero out the colour system before any help is rendered.
# (Non-TTY output is already ANSI-free: rich auto-strips colour on a pipe, and
# we deliberately do NOT override that — it would defeat FORCE_COLOR/CI signals.)
# This does not affect interactive use where NO_COLOR is absent.
# Agents: set NO_COLOR=1 for ANSI-free help, or use `schema` for structured output.
if os.environ.get("NO_COLOR"):
    typer.rich_utils.COLOR_SYSTEM = None

from .client import PlanClient
from .commands import config as config_cmd
from .commands import doc, phase, section, task
from .commands import doctor as doctor_cmd
from .commands import project as project_cmd
from .commands import schema as schema_cmd
from .commands import search as search_cmd
from .config import read_config
from .context import AppContext
from .errors import ExitCode, _emit_error

app = typer.Typer(name="claudeplans", no_args_is_help=True)

app.add_typer(doc.app, name="doc")
app.add_typer(phase.app, name="phase")
app.add_typer(task.app, name="task")
app.add_typer(section.app, name="section")
app.add_typer(project_cmd.app, name="project")
app.add_typer(config_cmd.app, name="config")
app.command("doctor")(doctor_cmd.doctor)
app.command("search")(search_cmd.search)
app.command("schema")(schema_cmd.schema)

# Options default to None so precedence is resolved manually in _root:
# explicit flag > CLAUDEPLANS_* env var > config file > built-in default.
# The explicit flag names are required; envvar binding is intentionally omitted so
# the resolution chain in _root stays explicit and testable.
_URL = typer.Option("--url")
_UID = typer.Option("--uid")
_FULL = typer.Option("--full", "-v", help="Print the full document on write replies.")


def build_client(url: str) -> PlanClient:
    """Build the client for a service URL (a seam tests monkeypatch)."""
    return PlanClient(url)


@app.callback()
def _root(
    ctx: typer.Context,
    url: Annotated[str | None, _URL] = None,
    uid: Annotated[str | None, _UID] = None,
    full: Annotated[bool, _FULL] = False,
) -> None:
    """Agent client for the claudeplans service."""
    cfg = read_config()
    resolved_url = (
        url
        or os.environ.get("CLAUDEPLANS_URL")
        or cfg.get("url")
        or "http://127.0.0.1:8000"
    )
    resolved_uid = uid or os.environ.get("CLAUDEPLANS_UID") or cfg.get("uid") or "dev"
    try:
        client = build_client(resolved_url)
    except httpx.InvalidURL as exc:
        # InvalidURL is not a RequestError subclass; it fires at Client construction
        # when the URL is structurally invalid (NUL byte, etc.). Emit a structured
        # transport error so the caller never sees a traceback.
        _emit_error({"error": "transport", "detail": str(exc)})
        raise typer.Exit(ExitCode.TRANSPORT) from exc
    ctx.obj = AppContext(
        client=client,
        uid=resolved_uid,
        base_url=resolved_url,
        full=full,
    )


def main() -> None:
    """Console-script entrypoint (see [project.scripts] in pyproject.toml)."""
    app()


if __name__ == "__main__":
    main()
