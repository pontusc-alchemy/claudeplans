# Brief 02 — The served/indexed content root is operator-selectable via PLANS_SRC

## INTENDED_GOAL (this session)

When the operator sets a `PLANS_SRC` environment variable before launching the plans
site, the site serves and indexes content from that directory instead of the built-in
default. When `PLANS_SRC` is unset, the site serves from the existing default. This
must hold for the macOS Tier-0 serve flow.

## Measurable success

Observable by a `browser-user` (or HTTP) verification dispatch against the running site
on this machine:

- With `PLANS_SRC` pointed at an arbitrary existing directory and the site launched, a
  content file that exists **only** in that directory is reachable through the running
  server, and the home/index reflects that directory's contents.
- Evidence the root actually moved: a file present only in the old default location is
  **not** served while `PLANS_SRC` points elsewhere.
- With `PLANS_SRC` unset, the site serves from the prior default — the default-case
  behavior is unchanged.
- Confirmed by an actual run on this host (browser or HTTP fetch), not by source
  inspection alone.

## What success does NOT prescribe

(Implementation freedom — enumerate liberally; do not narrow by inference.)

- The mechanism by which the variable takes effect: Makefile variable, config-template
  substitution, MkDocs-native env interpolation, a wrapper, or any combination.
- Whether the build/output directory is also relocated, and how.
- Whether the variable is consumed at config-render time, at serve time, or both.
- The variable's precedence details beyond "chosen when set, default when unset"
  (e.g. whether a command-line override also works).
- Whether other existing path-related variables are refactored in the process.

## Hard requirements

(World-constraints only.)

- Any changes live **only** under `plugins/plan/server/`. No other part of the repo is
  modified.
- With `PLANS_SRC` unset, the served root is the same default the site uses today.
- No hardcoded absolute user paths (e.g. `/Users/<name>/…`) introduced into committed
  repo files; the default is expressed via `$HOME`/repo-relative/dynamic resolution.
- The macOS Tier-0 flow (`make serve`) remains the supported way to run the site, and
  success is demonstrated by an actual run on this machine.

## Starting friction state

`unidentified` → first dispatch is DIAGNOSE.

Observed symptom to confirm/refute, not a prescribed fix: the served root is presently
fixed — the content path is materialized into the rendered MkDocs config at config time,
and the Makefile path variables are not currently overridable from the environment.

## Out of scope

- Making `.html` documents first-class/discoverable — that is Brief 01; do not pursue it
  here.
- Adding new server tiers (launchd, system services) or non-macOS packaging.
- Authentication or remote deployment.

Anti-clause: "Out of scope" does NOT silently include any particular mechanism for
honoring the variable, nor whether the output directory is also relocated. Those remain
open implementation choices for the orchestrator.

## Project context (inventory, not prescription)

- The site is **MkDocs Material**, served on this macOS host via the Tier-0 path
  `make serve` (foreground, http://127.0.0.1:8001). Relevant files all under
  `plugins/plan/server/`:
  - `Makefile` — defines path variables (`PLANS_DIR`, `PLANS_SRC`, `CONFIG_DIR`, …) and
    the `config`/`venv`/`serve`/`build` targets. The `config` target renders the MkDocs
    config from a template by substituting environment values via a small Python
    `string.Template` step, then serve runs MkDocs against the rendered config.
  - `mkdocs.yml.tmpl` — MkDocs config template; `docs_dir`/`site_dir` currently resolve
    under `~/plans/…`.
- Default content root today is `~/plans/src`; the built site goes to `~/plans/site`;
  the rendered config and venv live under `~/.config/plans-server/`.
- A site already exists on disk from prior runs; a stale server may be bound to port
  8001 — the orchestrator owns starting/stopping the server it verifies against.
- Note: the rendered MkDocs config is generated at `make config` time, so any value the
  operator wants honored must be present for the invocation that renders config (the
  `serve` target depends on `config`).
