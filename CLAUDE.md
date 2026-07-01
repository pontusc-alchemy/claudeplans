# claudeplans — project instructions

## Git

- Running `git commit` **is acceptable in this repository** — this overrides the
  global "no git state changes" rule. Stage and commit local changes here when
  the work is ready and the user has asked for a commit (commit only on request;
  if on the default branch, branch first).
- Pushing, deploys, and remote/prod changes remain the user's action — do **not**
  `git push` or modify remotes.

## Code intelligence

- `ty` LSP is wired up for Python via the project-local `lsp-workspace@skills-dir`
  plugin (`.claude/skills/lsp-workspace/`). Prefer the `LSP` tool over grep for
  symbol-level queries on `.py`/`.pyi` files.
