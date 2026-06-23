"""Domain error types and their exit-code mapping, shared by service and CLI.

WHY one home: storage raises StaleRevision/NotFound, the API maps them to HTTP
status codes, and claudeplans-cli maps them to process exit codes. A single definition
keeps all three layers consistent. ValidationError here is the DOMAIN error,
named to match the API/CLI contract in the plan; it is DISTINCT from
pydantic.ValidationError, so alias one of the two at any site that imports both.
"""

from enum import IntEnum


class PlanError(Exception):
    """Base class for all domain errors."""


class NotFound(PlanError):
    """The requested document/key does not exist."""


class StaleRevision(PlanError):
    """A conditional write lost the compare-and-set race (rev mismatch)."""


class CorruptDocument(PlanError):
    """A persisted document/envelope is malformed (bad rev, missing/garbled keys).

    A server-side data-integrity fault (e.g. a hand-edited file), distinct from a
    client error — the API maps it to 500 with a clean message, never a raw
    ValueError/KeyError stacktrace.
    """


class ValidationError(PlanError):
    """Structural validation of a document failed (the API maps this to HTTP 422).

    Distinct from pydantic.ValidationError; alias one at sites that import both.
    """


class Forbidden(PlanError):
    """A write outside the caller's namespace (write-own violation)."""


class ExitCode(IntEnum):
    """claudeplans-cli process exit codes (agent-client phase wires these to errors)."""

    OK = 0
    NOT_FOUND = 2
    FORBIDDEN = 3
    VALIDATION = 4
    STALE_REV = 9
