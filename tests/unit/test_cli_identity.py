"""Unit cases for the CLI's uid derivation (`claudeplans_cli.identity`) — every
case injects `home`/`env`, so none touch the real filesystem or environment."""

from pathlib import Path

import pytest

from claudeplans.auth.identity import slugify as server_slugify
from claudeplans_cli.identity import FLOOR, derive_uid, resolve_uid
from claudeplans_contracts.keys import validate_key_segment

_NO_ENV: dict[str, str] = {}


# --- derive_uid: the machine's user ---


@pytest.mark.parametrize("home", ["/Users/alek", "/home/alek"])
def test_derives_the_home_owner_on_both_platform_layouts(home: str) -> None:
    assert derive_uid(Path(home), _NO_ENV) == "alek"


@pytest.mark.parametrize(
    "home",
    ["/Users/Alek Ellegard", "/Users/alek.ellegard", "/Users/alek-ellegard"],
)
def test_slugification_is_lossy_and_collides_by_design(home: str) -> None:
    """Three distinct logins map onto one namespace — a safety property.

    The alternative is emitting a name that is not a valid key segment.
    """
    assert derive_uid(Path(home), _NO_ENV) == "alek-ellegard"


@pytest.mark.parametrize(
    "home",
    ["/home/eng/alek", "/export/home/alek", "/home/DOMAIN/alek"],
)
def test_nested_home_roots_still_derive(home: str) -> None:
    """The trusted-root test matches any ancestor, not the immediate parent.

    An exact-parent test would drop these into the shared floor silently, which
    is the failure mode this rule exists to prevent.
    """
    assert derive_uid(Path(home), _NO_ENV) == "alek"


@pytest.mark.parametrize("home", ["/", "/root", "/app", "/home"])
def test_abstains_on_a_bare_role_home(home: str) -> None:
    assert derive_uid(Path(home), _NO_ENV) is None


@pytest.mark.parametrize("home", ["/var/empty", "/nonexistent", "/opt/svc"])
def test_abstains_when_no_trusted_root_is_an_ancestor(home: str) -> None:
    assert derive_uid(Path(home), _NO_ENV) is None


@pytest.mark.parametrize(
    "home",
    ["/Users/runner", "/home/nobody", "/home/ubuntu", "/home/ec2-user"],
)
def test_abstains_on_a_service_login(home: str) -> None:
    """These slugify cleanly, so only the denylist catches them."""
    assert derive_uid(Path(home), _NO_ENV) is None


@pytest.mark.parametrize("home", ["/Users/Runner", "/Users/EC2-User", "/home/ROOT"])
def test_denylist_catches_case_and_punctuation_variants(home: str) -> None:
    """The denylist runs on the slug, so variants normalise onto the denied form.

    Checking raw `home.name` instead would let `/Users/Runner` straight through.
    """
    assert derive_uid(Path(home), _NO_ENV) is None


@pytest.mark.parametrize("marker", ["CI", "GITHUB_ACTIONS", "GITLAB_CI"])
def test_abstains_under_any_ci_marker(marker: str) -> None:
    assert derive_uid(Path("/Users/alek"), {marker: "true"}) is None


@pytest.mark.parametrize("home", ["/Users/名前", "/Users/---", "/home/!!!"])
def test_abstains_when_nothing_slug_safe_remains(home: str) -> None:
    assert derive_uid(Path(home), _NO_ENV) is None


@pytest.mark.parametrize(
    "home",
    ["/Users/alek", "/Users/Alek Ellegard", "/home/eng/alek", "/Users/a.b_c-d"],
)
def test_every_derived_value_is_a_valid_key_segment(home: str) -> None:
    """Derived uids become the `owner` segment of `owner/project/slug`."""
    derived = derive_uid(Path(home), _NO_ENV)
    assert derived is not None
    assert validate_key_segment(derived) == derived


@pytest.mark.parametrize(
    "name",
    [
        "alek",
        "Alek Ellegard",
        "alek.ellegard",
        "A B  C",
        "ÅÄÖ-x",
        "user_name",
        "9lives",
    ],
)
def test_slug_rule_matches_the_server_slugify(name: str) -> None:
    """The CLI copy and the server's rule must not silently diverge.

    They cannot share code — `cli` and `server` are sibling workspace members —
    so this table is what pins them together.
    """
    derived = derive_uid(Path("/Users") / name, _NO_ENV)
    try:
        expected = server_slugify(name)
    except ValueError:
        assert derived is None
    else:
        assert derived == expected


# --- resolve_uid: the full precedence chain ---


def test_flag_beats_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/Users/alek")))
    env = {"CLAUDEPLANS_UID": "from-env", "CLAUDEPLANS_DERIVE_UID": "1"}
    assert resolve_uid("from-flag", "from-config", env) == "from-flag"


def test_env_beats_config_and_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/Users/alek")))
    env = {"CLAUDEPLANS_UID": "from-env", "CLAUDEPLANS_DERIVE_UID": "1"}
    assert resolve_uid(None, "from-config", env) == "from-env"


def test_config_beats_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anyone who has run `config set --uid` never reaches the derived rung."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/Users/alek")))
    env = {"CLAUDEPLANS_DERIVE_UID": "1"}
    assert resolve_uid(None, "from-config", env) == "from-config"


def test_derivation_wins_over_the_floor_when_gated_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/Users/alek")))
    assert resolve_uid(None, None, {"CLAUDEPLANS_DERIVE_UID": "1"}) == "alek"


def test_gate_unset_reproduces_the_pre_derivation_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole opt-in stance: no gate, no behaviour change."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/Users/alek")))
    assert resolve_uid(None, None, _NO_ENV) == FLOOR
    assert resolve_uid(None, None, {"CLAUDEPLANS_DERIVE_UID": "0"}) == FLOOR
    assert resolve_uid(None, None, {"CLAUDEPLANS_DERIVE_UID": "true"}) == FLOOR


def test_abstain_with_the_gate_set_falls_to_the_floor_loudly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Setting the gate asks for derivation, so abstaining must not be silent."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/runner")))
    assert resolve_uid(None, None, {"CLAUDEPLANS_DERIVE_UID": "1"}) == FLOOR
    err = capsys.readouterr().err
    assert "CLAUDEPLANS_DERIVE_UID" in err
    assert FLOOR in err


def test_abstain_without_the_gate_is_silent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/runner")))
    assert resolve_uid(None, None, _NO_ENV) == FLOOR
    assert capsys.readouterr().err == ""
