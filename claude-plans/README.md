# claude-plans

A Claude Code plugin (`plan`) and its marketplace (`plans`) for a research → plan → iterate → review document lifecycle, rendered locally as a browsable dark-themed site at **http://plans.claude** via MkDocs Material + Caddy.

Documents live at `~/plans/src/projects/<project>/<slug>.md`; the landing page is generated, grouped by project. Two cornerstones: `type: research` (full consideration) and `type: plan` (phased execution with in-document learnings).

## Install

```shell
/plugin marketplace add ~/repos/claude-plans   # or the GitHub repo
/plugin install plan@plans
/plan:setup                                     # installs the local render stack
```

`/plan:setup` may print a hint to run `make -C <plugin>/server system-install` (sudo) for the `/etc/hosts` entry + Caddy unit — run that yourself. Re-run `/plan:setup` after each `/plugin marketplace update plans`.

## Skills

- `/plan:setup` — install/upgrade/repair the local rendering stack.
- `/plan:research <project> <topic>` — gather and present findings (`type: research`).
- `/plan:write <project> [research-slug]` — turn research/discussion into a phased plan (`type: plan`).
- `/plan:prime <project|slug>` — restore session context from a saved doc (model-invocable).
- `/plan:iterate <plan>` — execute a plan phase by phase; checks off tasks, records learnings.
- `/plan:review <plan>` — reconcile a plan against reality; revise in place on approval.

## Layout

```text
.claude-plugin/marketplace.json   # marketplace "plans"
plugins/plan/
├── .claude-plugin/plugin.json    # plugin "plan" (commit-SHA versioned, no version field)
├── skills/{setup,research,write,prime,iterate,review}/SKILL.md
├── templates/{research.md,plan.md}   # output contracts
└── server/                        # render infra → ~/.config/plans-server/ via `make install`
    ├── Makefile mkdocs.yml.tmpl gen_index.py extra.css
    ├── AUTHORING.md requirements.txt Caddyfile
    └── plans-render.service plans.service
```

## Provenance

Migrated from the dotfiles `claude-plans` stow package (render infra) and the standalone `present-research`, `present-plan`, `review-plan`, and `prime` (plan half) skills, now unified under one plugin.
