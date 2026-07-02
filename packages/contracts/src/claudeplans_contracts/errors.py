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
    """A conditional write lost the compare-and-set race (rev mismatch).

    `current_rev` is the server-side revision at the time of rejection; the
    caller can retry immediately without a re-read.
    """

    def __init__(self, key: str = "", current_rev: str = "") -> None:
        super().__init__(key)
        self.current_rev = current_rev


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


class InvalidRev(PlanError):
    """A client-supplied rev token is malformed (not a decimal integer string).

    A standalone subclass of PlanError (NOT ValidationError) so the CLI's
    isinstance-iteration mapping can't accidentally shadow it under the generic
    validation kind. A client input error, distinct from StaleRevision: a bad rev
    must never masquerade as a concurrency conflict. Maps to HTTP 400 and CLI exit
    code VALIDATION (4) with stderr kind "invalid_rev".
    """


def validate_rev(value: str) -> str:
    """Validate a rev token is well-formed: non-empty, ASCII decimal digits only.

    Revs are monotonic integer-as-string counters; anything else (empty, non-ASCII
    digits, or a stray JSON/text blob) is a malformed client input, not a
    concurrency conflict, so it is rejected here rather than falling through to a
    StaleRevision comparison.
    """
    if not value.isascii() or not value.isdigit():
        raise InvalidRev(f"malformed rev {value!r}: expected ASCII decimal digits")
    return value


class ExitCode(IntEnum):
    """claudeplans-cli process exit codes (agent-client phase wires these to errors).

    `2` is RESERVED by Typer/Click for malformed command lines (bad flag, missing
    arg, bad enum, misplaced global option) and is never raised by us, so domain
    failures avoid it: NOT_FOUND lives at `5` so a genuine not-found is
    distinguishable from a usage error.
    """

    OK = 0
    ERROR = 1  # generic failure: an unmapped PlanError (e.g. CorruptDocument)
    USAGE = 2  # reserved by Typer/Click for usage errors; never raised by us
    FORBIDDEN = 3
    VALIDATION = 4
    NOT_FOUND = 5
    TRANSPORT = 6  # the service could not be reached (connect/timeout/DNS failure)
    STALE_REV = 9
