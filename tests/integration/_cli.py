"""Shared non-fixture helpers for the CLI end-to-end test files."""

import json

from typer.testing import CliRunner, Result

from claudeplans_contracts import ExitCode

runner = CliRunner()

VALID_CREATE = json.dumps(
    {
        "type": "plan",
        "slug": "p1",
        "title": "Plan One",
        "phases": [{"slug": "a", "name": "Alpha", "tasks": [{"text": "t1"}]}],
    }
)


# Each invalid-input path is a clean exit 4 (VALIDATION) with a structured stderr
# error, never a 500 / traceback and never a silent write.
def assert_validation_exit(result: Result) -> None:
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"
