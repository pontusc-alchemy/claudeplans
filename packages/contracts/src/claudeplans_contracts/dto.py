"""Wire DTOs shared by the service and the CLI."""

from pydantic import BaseModel


class DriftWarning(BaseModel):
    """An item in the shared {data, warnings[]} envelope.

    Named DriftWarning rather than Warning to avoid shadowing the builtin. Produced
    by the server's drift linter, consumed by the CLI.

    `path` is a dotted locator into the document: "phases.<slug>" for a phase-scoped
    warning, None for a document-level warning. The CLI parses this, so the grammar
    is a contract; it keys phases by slug, which is why phase slugs must be unique
    (see models.py Document._check_invariants).
    """

    code: str
    message: str
    path: str | None = None
