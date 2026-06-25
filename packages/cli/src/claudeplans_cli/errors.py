"""Domain-error -> process-exit-code mapping and the command error boundary.

WHY here: the CLI's contract with calling agents is its exit code. A raised domain
error (NotFound/Forbidden/...) or a client-side pydantic ValidationError must become
a stable, scriptable exit code — never a stacktrace. `handle_errors` is the single
boundary every command wears so that contract is enforced in one place.
"""

import functools
import json
from collections.abc import Callable

import httpx
import typer
from pydantic import ValidationError as PydanticValidationError

from claudeplans_contracts import (
    ExitCode,
    Forbidden,
    NotFound,
    PlanError,
    StaleRevision,
    ValidationError,
)

_ERROR_TO_EXIT: dict[type[PlanError], ExitCode] = {
    NotFound: ExitCode.NOT_FOUND,
    Forbidden: ExitCode.FORBIDDEN,
    ValidationError: ExitCode.VALIDATION,
    StaleRevision: ExitCode.STALE_REV,
}

# The machine-readable `error` kind printed on stderr for each domain error, paired
# with the exit code above. An unmapped PlanError (CorruptDocument, the base) reports
# the generic "error" kind, matching its ExitCode.ERROR.
_ERROR_TO_KIND: dict[type[PlanError], str] = {
    NotFound: "not_found",
    Forbidden: "forbidden",
    ValidationError: "validation",
    StaleRevision: "stale_rev",
}


def exit_code_for(exc: PlanError) -> int:
    """Map a domain error to its exit code.

    An unmapped PlanError (CorruptDocument, the PlanError base) is a generic
    failure: not client-correctable, so it gets ExitCode.ERROR rather than
    masquerading as a validation problem.
    """
    for error_cls, code in _ERROR_TO_EXIT.items():
        if isinstance(exc, error_cls):
            return int(code)
    return int(ExitCode.ERROR)


def kind_for(exc: PlanError) -> str:
    """Map a domain error to its machine-readable `error` kind (see _ERROR_TO_KIND)."""
    for error_cls, kind in _ERROR_TO_KIND.items():
        if isinstance(exc, error_cls):
            return kind
    return "error"


def _emit_error(payload: dict[str, object]) -> None:
    """Print a compact, single-line JSON error object to stderr (never a traceback)."""
    typer.echo(json.dumps(payload, separators=(",", ":")), err=True)


def handle_errors[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Wrap a Typer command, converting domain/validation/transport errors into
    typer.Exit, always emitting a compact `{"error":"<kind>",…}` JSON line on stderr
    so an agent can branch on the failure without parsing prose — and never sees a
    traceback.

    - StaleRevision -> `{"error":"stale_rev","current_rev":"<N>"}`, exit STALE_REV
      (the rev lets the agent retry without a re-read).
    - any other domain `PlanError` -> `{"error":"<kind>","detail":…}`, its mapped exit.
    - client-side pydantic `ValidationError` (a malformed create body) ->
      `{"error":"validation","detail":…}`, exit VALIDATION.
    - `httpx.InvalidURL` — a malformed --url or URL-construction failure (subclasses
      Exception, not RequestError, so it must be caught separately). Mapped to
      TRANSPORT: it is a "can't reach the service" class of failure, not a usage error,
      and consistent with the RequestError catch below.
    - any `httpx.RequestError` — the request could not be completed against the
      service (connect/timeout/DNS, but also decoding/redirect/protocol faults) ->
      `{"error":"transport",…}`, exit TRANSPORT. This is the whole request-side
      hierarchy *except* `HTTPStatusError`, which the client already converts to a
      domain error via `_raise_for_status`; catching the base keeps the "never a
      traceback" promise airtight rather than letting a non-transport sibling escape.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except StaleRevision as exc:
            _emit_error({"error": "stale_rev", "current_rev": exc.current_rev})
            raise typer.Exit(ExitCode.STALE_REV) from exc
        except PlanError as exc:
            _emit_error({"error": kind_for(exc), "detail": str(exc)})
            raise typer.Exit(exit_code_for(exc)) from exc
        except PydanticValidationError as exc:
            _emit_error({"error": "validation", "detail": str(exc)})
            raise typer.Exit(ExitCode.VALIDATION) from exc
        except httpx.InvalidURL as exc:
            # InvalidURL is not a RequestError subclass; must be caught separately.
            _emit_error({"error": "transport", "detail": str(exc)})
            raise typer.Exit(ExitCode.TRANSPORT) from exc
        except httpx.RequestError as exc:
            _emit_error({"error": "transport", "detail": str(exc)})
            raise typer.Exit(ExitCode.TRANSPORT) from exc

    return wrapper
