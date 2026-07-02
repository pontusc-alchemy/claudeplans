# claudeplans — project instructions

## Git

- Running `git commit` **is acceptable in this repository** — this overrides the
  global "no git state changes" rule. Stage and commit local changes here when
  the work is ready and the user has asked for a commit (commit only on request;
  if on the default branch, branch first).
- Pushing, deploys, and remote/prod changes remain the user's action — do **not**
  `git push` or modify remotes.
- **Feature-branch workflow.** Each piece of work gets its own branch off
  `master` (create it with `git branch <feature> master` before the first
  commit). Merge back by fast-forwarding master without a checkout:
  `git fetch . <feature>:master` (refuses non-ff, leaves the working tree
  alone). Note: `git checkout` / `git switch` / `git tag` are on the deny
  list — hand those to the user.
- **Releases** are tagged `vX.Y.Z` on `master` and consumed by the Claude Code
  plugin (marketplace pinned to the tag; the CLI ships as a `bin/` uvx shim
  pinned to a commit SHA). Cutting one (manual, mirrors the README): land all
  `packages/` changes and note the resulting SHA → set that SHA in
  `plugins/plan/bin/claudeplans` and bump `version` in
  `plugins/plan/.claude-plugin/plugin.json` → commit → the user tags that
  commit on master and pushes branch + tag.

## Local stacks

- **`make serve` = the stable stack** — compose project `claudeplans`, which keys
  the long-lived `claudeplans_data`/`claudeplans_state` volumes and takes its bind
  from the checkout's env file. Run it only from the pinned release worktree
  (user-created; e.g. `../claudeplans.worktrees/serve`), never from the dev tree —
  that would rebuild the stable stack from dev source.
- **`make up` / `make down` = the dev stack** — default compose project
  `claudeplans-dev`, own disposable volumes, bind hard-coded to `127.0.0.1:9394`
  in the recipe. Safe to cycle freely, including a volume wipe of that project.
- Running these local stacks (`make serve`/`make up`/`make down` and compose
  commands against them) **is the agreed exemption** to the global "never run
  state-changing commands" rule. Everything else that rule covers stays barred.

## Interactions

- This project uses a Makefile for all interactions. To run tests, formatting, linting, builds or anything similar check what exists in the Makefile. If something is missing, add it.

## Code intelligence

- `ty` LSP is wired up for Python via the project-local `lsp-workspace@skills-dir`
  plugin (`.claude/skills/lsp-workspace/`). Prefer the `LSP` tool over grep for
  symbol-level queries on `.py`/`.pyi` files.
