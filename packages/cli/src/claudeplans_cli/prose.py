"""Shared prose-field resolution for CLI commands (inline vs --<flag>-file/stdin)."""

import sys
from pathlib import Path

from claudeplans_contracts import ValidationError


def resolve_prose(inline: str | None, path: str | None, flag: str) -> str | None:
    """Resolve a prose field from its inline value or a file/stdin path.

    Returns the inline value when no file path is given (None = leave unchanged).
    `-` reads stdin. Passing both the inline flag and its --<flag>-file is a usage
    error. A missing/unreadable/non-UTF-8 file (or stdin) surfaces as a domain
    ValidationError (exit 4) via the handle_errors boundary, never a traceback.
    """
    if path is None:
        return inline
    if inline is not None:
        raise ValidationError(f"pass either --{flag} or --{flag}-file, not both")
    try:
        if path == "-":
            return sys.stdin.read()
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(f"--{flag}-file: {exc}") from exc
