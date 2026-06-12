---
name: prime
description: Bootstrap session context from a saved plans document or project. Given a project name, enumerate its docs and brief from the active ones; given a slug, brief that document.
user-invocable: true
model-invocable: true
allowed-tools: Bash, Agent
model: sonnet
---

Load context from a saved document under `~/plans/src/projects/` by delegating the reads to an agent — never read large files in the main thread. The argument is a project name or a slug.

## Resolve the source

```shell
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" resolve "<arg>"
```

→ JSON `{kind, docs}`; non-zero exit → relay stderr and stop.

- `kind: project` → brief the `status: active` docs; if several are active brief all, if none are present the list and ask.
- `kind: doc` → brief that document.
- `kind: ambiguous` → present the candidates and ask. Don't guess.
- Bare invocation (no argument) → `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" list` and present the tree.

For each `type: plan` doc, get the current phase deterministically:

```shell
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" phases <slug>
```

→ `{current, phases:[{n,name,anchor,pill,tasks}]}`.

## Brief (delegate)

Spawn one `Agent` (`general-purpose`, `sonnet`) to read the resolved doc(s) and return a DENSE briefing — the `phases` output already supplies the current phase and task states, so the agent focuses on:

- title + intro; section list (level-2 `##`) in order;
- locked decisions (`<span class="pill ok">`);
- open gaps/caveats (`pill gap` / `pill partial` spans, `!!! warning` / `!!! danger` admonitions);
- verbatim config / commands / paths / version pins.

Relay the result as restored context and continue.
