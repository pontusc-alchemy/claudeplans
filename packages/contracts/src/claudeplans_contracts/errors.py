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


class ValidationError(PlanError):
    """Structural validation of a document failed (the API maps this to HTTP 422).

    Distinct from pydantic.ValidationError; alias one at sites that import both.
    """


class ExitCode(IntEnum):
    """claudeplans-cli process exit codes (agent-client phase wires these to errors)."""

    OK = 0
    NOT_FOUND = 2
    VALIDATION = 4
    STALE_REV = 9
