"""`claudeplans config <verb>` — read/write the XDG config file.

`config set` persists url/uid so callers don't need flags on every invocation.
`config show` prints the effective resolved values (flag > env > config > default)
without making any network request.

Typer descriptors are module-level singletons to satisfy ruff B008.
"""

import json
import os
from typing import Annotated

import typer

from claudeplans_contracts import ValidationError

from ..config import config_path, read_config, write_config
from ..context import AppContext
from ..errors import handle_errors

app = typer.Typer(no_args_is_help=True)

_URL_OPT = typer.Option("--url")
_UID_OPT = typer.Option("--uid")


@app.callback()
def _callback() -> None:
    """Manage the local claudeplans CLI configuration."""


def _validate_config_value(name: str, value: str) -> None:
    """Raise ValidationError if value is empty, contains a control character,
    or is not valid UTF-8."""
    if not value:
        raise ValidationError(f"{name}: value must not be empty")
    for ch in value:
        if ord(ch) < 0x20 or ch == "\x7f":
            raise ValidationError(f"{name}: value must not contain control characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValidationError(f"{name}: value must be valid UTF-8") from None


@app.command()
@handle_errors
def set(
    url: Annotated[str | None, _URL_OPT] = None,
    uid: Annotated[str | None, _UID_OPT] = None,
) -> None:
    """Persist --url and/or --uid to the config file (merged into existing)."""
    if url is None and uid is None:
        typer.echo("error: at least one of --url or --uid is required", err=True)
        raise typer.Exit(1)
    if url is not None:
        _validate_config_value("url", url)
    if uid is not None:
        _validate_config_value("uid", uid)
    path = write_config(url, uid)
    print(str(path))


@app.command()
@handle_errors
def show(ctx: typer.Context) -> None:
    """Print the effective url/uid the CLI would use (no network request)."""
    cfg = read_config()
    effective_url = (
        os.environ.get("CLAUDEPLANS_URL") or cfg.get("url") or "http://127.0.0.1:8000"
    )
    # Read back what the root callback resolved rather than recomputing the chain,
    # so this window cannot drift from the uid the CLI actually writes as.
    context: AppContext = ctx.obj
    print(
        json.dumps(
            {
                "path": str(config_path()),
                "url": effective_url,
                "uid": context.uid,
            },
            separators=(",", ":"),
        )
    )
