"""Resolve which namespace (uid) an invocation targets — see `resolve_uid` for the
precedence chain and `derive_uid` for the machine-derived rung within it."""

import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final

type Env = Mapping[str, str] | None

# The only uid the shipped noop auth provider accepts; the chain's last resort.
FLOOR: Final = "dev"

# Opt-in gate. Unset reproduces the pre-derivation default exactly.
DERIVE_GATE: Final = "CLAUDEPLANS_DERIVE_UID"

# Behaviourally identical to `slugify` in the server's auth/identity.py; copied
# because `server` and `cli` are siblings. A parity test pins the two together.
_NON_SLUG = re.compile(r"[^a-z0-9]+")

# Presence of any of these means no human owns this machine.
_CI_MARKERS: Final = ("CI", "GITHUB_ACTIONS", "GITLAB_CI")

# Home paths that name a machine role rather than a person.
_BARE_HOMES: Final = frozenset({Path("/"), Path("/root"), Path("/app"), Path("/home")})

# Matched by NAME anywhere in the ancestor chain, so relocated and nested layouts
# (`/export/home/alek`, `/home/eng/alek`) derive instead of abstaining silently.
_HOME_ROOT_NAMES: Final = frozenset({"Users", "home"})

# Checked AFTER slugification, so case variants (`/Users/Runner`) normalise onto
# the denied form first.
_DENIED_LOGINS: Final = frozenset(
    {"root", "app", "runner", "nobody", "ubuntu", "ec2-user"}
)


def _slugify(name: str) -> str:
    """Lowercase slug of `name`: non-[a-z0-9] runs -> '-', edges stripped.

    Raises ValueError if nothing slug-safe remains.
    """
    slug = _NON_SLUG.sub("-", name.casefold()).strip("-")
    if not slug:
        raise ValueError(f"name {name!r} has no slug-safe characters")
    return slug


def derive_uid(home: Path | None = None, env: Env = None) -> str | None:
    """The machine's user as a storage-key-safe slug, or None to abstain.

    Reads the home-directory OWNER (`/Users/alek` -> `"alek"`), never the current
    working directory: cwd is process state that changes the moment an agent cd's
    into a worktree or `/app`, while the home path identifies the machine's user
    for the whole invocation.

    Pure and total — `home` and `env` are injectable, so every branch is testable
    without touching the real filesystem or environment. Abstains with None on CI,
    a role home, untrusted ancestry, an unslugifiable name, or a service login,
    leaving the caller's `"dev"` floor in place.

    Trusted ancestry is a directory NAMED `Users` or `home` anywhere above the
    home dir. An immediate-parent test would abstain on every nested or relocated
    layout (`/home/eng/alek`, `/export/home/alek`), silently sharing one namespace
    between people — the worst outcome available to an identity default.

    Slugification is lossy by design: `Alek Ellegard`, `alek.ellegard` and
    `alek-ellegard` all yield `"alek-ellegard"`, so two logins can share a
    namespace. That keeps every result a valid `validate_key_segment` value
    (`claudeplans_contracts.keys`) by construction.

    Derivation is a default-TARGET convenience, not authentication: it chooses
    which namespace a request addresses, and the server's auth provider alone
    decides whether the write is allowed.
    """
    environ = os.environ if env is None else env
    if any(marker in environ for marker in _CI_MARKERS):
        return None

    resolved = Path.home() if home is None else home
    if resolved in _BARE_HOMES:
        return None
    if not any(parent.name in _HOME_ROOT_NAMES for parent in resolved.parents):
        return None

    try:
        slug = _slugify(resolved.name)
    except ValueError:
        return None
    return None if slug in _DENIED_LOGINS else slug


def resolve_uid(flag: str | None, cfg_uid: str | None, env: Env = None) -> str:
    """The namespace this invocation targets.

    Precedence: `--uid` > `CLAUDEPLANS_UID` > `config.toml uid` > derived > FLOOR.
    Derivation sits below all three explicit-intent layers and behind an opt-in
    gate, so anyone who has ever run `config set --uid` never reaches it and an
    unset gate reproduces the pre-derivation default byte for byte.

    Setting the gate is a request for derivation, so an abstain is announced on
    stderr. Staying silent there would reintroduce the very failure this guards
    against: landing in the shared floor namespace with no indication why.
    """
    environ = os.environ if env is None else env
    explicit = flag or environ.get("CLAUDEPLANS_UID") or cfg_uid
    if explicit:
        return explicit
    if environ.get(DERIVE_GATE) != "1":
        return FLOOR
    derived = derive_uid(env=environ)
    if derived is not None:
        return derived
    print(
        f"claudeplans: {DERIVE_GATE} is set but no uid could be derived from "
        f"{Path.home()}; using {FLOOR!r}",
        file=sys.stderr,
    )
    return FLOOR
