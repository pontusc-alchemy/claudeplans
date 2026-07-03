# plan — the Claude Code plugin

Packages the plan lifecycle as skills over the claudeplans service, plus the
`claudeplans` CLI itself as a `bin/` shim. Install via the marketplace pinned
to a release tag (see the root README's *Claude Code plugin* section).

## Skills

The lifecycle: `research` → `write` → `prime` → `iterate` → `review`, with
`update` for point edits and `setup` for machine provisioning.

| Skill | Intent |
| --- | --- |
| `/plan:research` | Research a topic into a structured findings doc — the reference cornerstone (why/options/gotchas). |
| `/plan:write` | Author an actionable implementation plan — the action cornerstone (what/how), often from a research doc. |
| `/plan:prime` | Bootstrap a session's context from an existing doc/project. |
| `/plan:iterate` | Execute a plan phase-by-phase: check off tasks, record learnings, mutate the doc as reality changes. |
| `/plan:review` | Reconcile a saved plan against reality after work happened without it; revise on approval. |
| `/plan:update` | Targeted direct edit to a saved doc (section, phase/task/doc status) on explicit request. |
| `/plan:setup` | Provision this machine as client (CLI shim + server address) or server (compose stack + hosts alias). |

## `bin/claudeplans`

A [uvx](https://docs.astral.sh/uv/guides/tools/) shim pinned to an exact
commit SHA — immutable to uv, so after the first run the CLI serves from
cache with no per-call network check (a tag ref would re-fetch every
invocation). Cutting a release bumps this SHA together with the `version` in
`.claude-plugin/plugin.json` (recipe in the root README).

## `AUTHORING.md`

Field-level reference for authoring documents through the CLI, used by the
authoring skills. Source of truth for every field:
`packages/contracts/src/claudeplans_contracts/models.py`.
