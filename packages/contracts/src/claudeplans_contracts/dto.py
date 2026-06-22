"""Wire DTOs shared by the service and the CLI."""

from pydantic import BaseModel


class DriftWarning(BaseModel):
    """An item in the shared {data, warnings[]} envelope.

    Named DriftWarning rather than Warning to avoid shadowing the builtin. Produced
    by the server's drift linter, consumed by the CLI.
    """

    code: str
    message: str
    path: str | None = None
