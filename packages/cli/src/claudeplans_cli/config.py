"""XDG config file reader/writer for the claudeplans CLI.

WHY: the CLI needs a persistent default url/uid so users don't pass flags on every
invocation. Standard XDG_CONFIG_HOME placement keeps it out of the home root.
Only two string keys are meaningful: `url` and `uid`. The file is hand-rolled TOML
(no third-party dep) because the schema is trivially simple.
"""

import os
import tempfile
import tomllib
from pathlib import Path


def config_path() -> Path:
    """Return the canonical config file path under XDG_CONFIG_HOME."""
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "claudeplans" / "config.toml"


def read_config() -> dict[str, str]:
    """Parse the config file; return {} if absent or unparseable.

    Tolerant by design: a broken config must not crash every CLI command.
    Only `url` and `uid` keys from the file are used by the CLI.
    """
    path = config_path()
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
        return {k: str(v) for k, v in data.items() if isinstance(v, str)}
    except Exception:
        return {}


def _escape_toml_string(value: str) -> str:
    """Escape special chars so the value is safe inside a TOML basic string.

    Backslash must be escaped first to avoid double-escaping the sequences
    introduced below.
    """
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def write_config(url: str | None, uid: str | None) -> Path:
    """Merge url/uid into the existing config and write it; return the path.

    Non-None arguments overlay the existing values; None arguments leave the
    existing value unchanged.

    The write is atomic: content is encoded and written to a temp file in the
    same directory, then os.replace() renames it into place. If encoding or
    writing fails the original config.toml is never truncated.
    """
    current = read_config()
    if url is not None:
        current["url"] = url
    if uid is not None:
        current["uid"] = uid

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for key in ("url", "uid"):
        if key in current:
            lines.append(f'{key} = "{_escape_toml_string(current[key])}"')

    content = ("\n".join(lines) + "\n" if lines else "").encode()
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path
