"""The claudeplans CLI entrypoint. Resource-grouped subcommands (`claudeplans <resource>
<verb>`) and the exit-code contract land in the agent-client phase; this skeleton
gives a runnable entrypoint.
"""

import typer

app = typer.Typer(name="claudeplans", no_args_is_help=True)


@app.callback()
def _root() -> None:
    """Agent client for the claudeplans service.

    A no-op root so the (currently command-less) app is invocable; resource
    sub-apps are registered in the agent-client phase.
    """


def main() -> None:
    """Console-script entrypoint (see [project.scripts] in pyproject.toml)."""
    app()


if __name__ == "__main__":
    main()
