# LLM.md — how to work in this repo

Guidance for coding agents and the humans driving them. The README covers what
the project *is*; this file covers how changes get made and land.

`AGENTS.md` and `CLAUDE.md` are symlinks to this file, so every tool reads the
same rules. Edit `LLM.md`.

## Orientation

- A [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
  with three members: `packages/contracts` (shared Pydantic models),
  `packages/server` (FastAPI CRUD service), `packages/cli` (CLI client), plus
  the Claude Code plan plugin under `plugins/plan/`.
- **Module intent maps**: `packages/{contracts,server,cli}/README.md` and
  `tests/README.md` give 1–2 lines per module on what belongs where — consult
  them before grepping blind, and update them when you add or repurpose a
  module.

## Interactions — the Makefile is the interface

All interactions go through the Makefile (`make help` lists everything). If a
task is missing a target, add one rather than documenting a raw command.

- Targets that need the venv depend on `make venv` themselves.
- **`make check` is the full quality gate** (ruff check + format --check + ty +
  pytest) — run it before proposing any commit. It is the same gate CI runs.
- Partial runs: `make lint` / `fmt` / `typecheck` / `test`.
- `make ci` runs the identical gate inside the `claudeplans:ci` Docker image
  against mounted source (matches `scripts/ci.sh`).

## Local stacks

- **`make up` / `make down`** — the dev stack (compose project
  `claudeplans-dev`), served on `127.0.0.1:9394` as the host user
  (`CLAUDEPLANS_NOOP_UID`, derived from `id -un`; unset means the fixed `dev`).
  Writes are own-namespace, so point the CLI at the same uid or it 403s.
  Disposable volumes; safe to cycle freely.
- **`make seed`** populates demo projects (`empty`/`atlas`/`beacon`)
  idempotently via `scripts/seed.py`; point it elsewhere with
  `CLAUDEPLANS_URL`.
- **`make serve`** — the stable stack (compose project `claudeplans`, long-lived
  volumes). Run it only from a pinned release worktree, never from a dev tree —
  that would rebuild the stable stack from dev source.
- Noop auth is unauthenticated by design: **never bind these stacks to anything
  other than loopback**.

## Python version

- Pinned to **`>=3.14,<3.15`** in every member's `pyproject.toml`; the Docker
  image is `python:3.14-slim`. All 3.14 syntax is in play.
- **PEP 758 is valid here — do not flag it.** Unparenthesized multi-exception
  handlers (`except KeyError, ValueError:`) are legal Python 3.14 syntax, not a
  Python-2 SyntaxError. Example in-tree:
  `packages/server/src/claudeplans/api/listing.py`.

## Git workflow

- **Feature branches off `master`**, one per piece of work. Changes land via
  pull request with a green **Quality gate** CI check and at least one
  approving review (enforced by the repository rulesets configured on GitHub:
  `protect-master` and `protect-release-tags`).
- **Master history is linear**: squash or rebase — merge commits are blocked
  by the ruleset.
- Never rewrite published history; never force-push shared branches.
- **Releases** are tagged `vX.Y.Z` on `master` (maintainer action) and consumed
  by the Claude Code plugin: the marketplace pins to the tag, and the CLI ships
  as a `bin/` uvx shim pinned to a commit SHA (immutable to uv, so the CLI
  serves from cache with no per-call network check — a tag ref would re-fetch
  on every invocation). Cutting one: land all `packages/` changes and note the
  resulting SHA → set that SHA in `plugins/plan/bin/claudeplans` and bump
  `version` in `plugins/plan/.claude-plugin/plugin.json` → commit → tag that
  commit on master → push branch and tag.

## Design & conventions

- **Package layering**: `contracts` depends on neither sibling; `server` and
  `cli` both depend on `contracts`; the CLI talks to the server only over HTTP
  via the shared models. Don't reach across these boundaries.
- **Where code belongs**: the module intent maps (above) are authoritative —
  extend the map when the answer isn't there yet.
- **Style is mechanical**: ruff (lint + format) and ty are the law; run
  `make fmt` instead of hand-formatting, and don't debate style in review —
  change the tool config in the workspace root `pyproject.toml` instead.
- **Tests land with behavior**: the `tests/{unit,integration,contract}` split
  is documented in `tests/README.md`; put new coverage at the matching layer.
- **Surgical changes**: every changed line should trace to the task at hand.
  Don't touch adjacent code, comments, or formatting; mention unrelated bugs
  instead of fixing them in the same change.
- **Docs earn their place**: let the code speak for itself. Working notes and
  status live outside the repo; `docs/` takes only what a maintainer has agreed
  to keep, because every page committed is a page that can go stale.
- **Dependencies are supply-chain risk**: pin to specific versions — Python
  packages via the workspace `uv.lock`, GitHub Actions by commit SHA (see
  `.github/workflows/`).
- **Declarative over imperative**: persistent state (infra, service config) is
  expressed as git-tracked declarative artifacts (compose, bake, workflows),
  not one-shot commands.

## Claude Code specifics

- The `ty` LSP is wired up for Python via the committed project-local
  `lsp-workspace@skills-dir` plugin (`.claude/skills/lsp-workspace/`). Prefer
  the `LSP` tool over grep for symbol-level queries on `.py`/`.pyi` files.
- Personal workflow rules (sandboxing, command deny-lists, machine-specific
  paths) belong in your own global config or an untracked `CLAUDE.local.md`,
  not in this file.
