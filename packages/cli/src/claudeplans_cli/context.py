"""The per-invocation application context carried on Typer's `ctx.obj`.

WHY its own module: the root app (cli.py) builds it and every command sub-app reads
it, so housing it apart from cli.py breaks the cli <-> commands import cycle.
"""

from dataclasses import dataclass

from .client import PlanClient


@dataclass
class AppContext:
    """The client and caller identity resolved once by the root callback."""

    client: PlanClient
    uid: str
    base_url: str
    full: bool = False
