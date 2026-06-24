"""Domain-error -> process-exit-code mapping and the command error boundary.

WHY here: the CLI's contract with calling agents is its exit code. A raised domain
error (NotFound/Forbidden/...) or a client-side pydantic ValidationError must become
a stable, scriptable exit code — never a stacktrace. `handle_errors` is the single
boundary every command wears so that contract is enforced in one place.
"""

import functools
import json
from collections.abc import Callable

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


def handle_errors[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Wrap a Typer command, converting domain/validation errors into typer.Exit.

    Domain `PlanError` -> its mapped exit code; client-side pydantic
    `ValidationError` (a malformed create body) -> ExitCode.VALIDATION. Both echo
    their message to stderr so the human/agent sees the cause without a traceback.

    StaleRevision is special: prints `{"error":"stale_rev","current_rev":"<N>"}` as
    compact JSON to stderr so the agent can retry without a re-read.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except StaleRevision as exc:
            payload = {"error": "stale_rev", "current_rev": exc.current_rev}
            typer.echo(json.dumps(payload, separators=(",", ":")), err=True)
            raise typer.Exit(ExitCode.STALE_REV) from exc
        except PlanError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(exit_code_for(exc)) from exc
        except PydanticValidationError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(ExitCode.VALIDATION) from exc

    return wrapper
