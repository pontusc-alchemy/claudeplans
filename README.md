# claude-plans

A Claude Code plugin (`plan`) and its marketplace (`plans`) for a research → plan → iterate → review document lifecycle, rendered locally as a browsable dark-themed site at **http://plans.claude** via MkDocs Material + Caddy.

Documents live at `~/plans/src/projects/<project>/<slug>.md`; the landing page is generated, grouped by project. Two cornerstones: `type: research` (full consideration) and `type: plan` (phased execution with in-document learnings).

An optional branch level groups docs by branch — `projects/<project>/<branch>/<slug>.md` — alongside flat `projects/<project>/<slug>.md`. Detection is structural: a `.md` **file** under a project is a flat slug; a **subdirectory** is a branch whose `.md` files are slugs. The branch level is capped at one (deeper nesting is not recognized as further branch levels). A subdirectory named `diagrams/` is reserved for generated `*.html` and is never treated as a branch — so a real git branch literally named `diagrams` would be swallowed by the diagram bucket.

## Install

```shell
/plugin marketplace add ~/repos/claude-plans   # or the GitHub repo
/plugin install plan@plans
/plan:setup                                     # installs the local render stack
```

The render stack installs in portability tiers: Tier 0 (any OS, no sudo) is config + venv + `make -C <plugin>/server serve` (foreground render at http://127.0.0.1:8001); Tier 1 (Linux/systemd) adds the per-user `plans-render` unit; Tier 2 (Linux/systemd, sudo) is `make -C <plugin>/server system-install` for the `/etc/hosts` entry + Caddy unit at http://plans.claude — run that yourself. On macOS only Tier 0 ships (launchd/hostname tiers are designed, not built). Templating uses `python3` (no `envsubst`/gettext dependency). Re-run `/plan:setup` after each `/plugin marketplace update plans`.

## Skills

- `/plan:setup` — install/upgrade/repair the local rendering stack.
- `/plan:research <project> <topic>` — gather and present findings (`type: research`).
- `/plan:write <project> [research-slug]` — turn research/discussion into a phased plan (`type: plan`).
- `/plan:prime <project|slug>` — restore session context from a saved doc (model-invocable).
- `/plan:iterate <plan>` — execute a plan phase by phase; checks off tasks, records learnings.
- `/plan:review <plan>` — reconcile a plan against reality; revise in place on approval.
- `/plan:update <doc> <change>` — make a targeted revision to a saved doc; bumps date and validates.

## Layout

```text
.claude-plugin/marketplace.json   # marketplace "plans"
plugins/plan/
├── .claude-plugin/plugin.json    # plugin "plan" (commit-SHA versioned, no version field)
├── AUTHORING.md                  # the agent authoring contract (read by skills)
├── skills/{setup,research,write,prime,iterate,review,update}/SKILL.md
├── scripts/plan-doc              # stdlib create/lookup/metadata/lint helper
├── templates/{research.md,plan.md}   # output contracts
└── server/                        # render infra → ~/.config/plans-server/ via `make install`
    ├── Makefile mkdocs.yml.tmpl gen_index.py extra.css index.md
    ├── requirements.txt Caddyfile
    └── plans-render.service plans.service.tmpl
```

Operational note: `gen_index.py` hook changes require `systemctl --user restart plans-render` to take effect; docs and config changes hot-reload.

## Provenance

Migrated from the dotfiles `claude-plans` stow package (render infra) and the standalone `present-research`, `present-plan`, `review-plan`, and `prime` (plan half) skills, now unified under one plugin.
