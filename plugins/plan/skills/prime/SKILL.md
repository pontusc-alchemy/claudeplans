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

- `kind: project` → brief the `status: active` docs; if several are active brief all, if none, present the list and ask.
- `kind: doc` → brief that document.
- `kind: ambiguous` → present the candidates and ask. Don't guess.
- `kind: none` → say no match and run `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" list` to present what exists.
- Bare invocation (no argument) → `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" list` and present the tree.

For each `type: plan` doc, get the current phase deterministically — pass the resolved `path`:

```shell
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" phases <path>
```

→ `{current, tally:{done,total,blocked}, phases:[{ordinal,slug,name,status,note,has_phase_class,tasks}]}`.

## Brief (delegate)

Spawn one `Agent` (`general-purpose`, `sonnet`) to read the resolved doc(s) and return a DENSE briefing — the `phases` output already supplies the current phase and task states, so the agent focuses on:

- title + intro; section list (level-2 `##`) in order;
- done phases / locked decisions (`status: done`, `<span class="pill done">`);
- open/blocked phases and caveats (`status: todo|doing|blocked`, `!!! warning` / `!!! danger` admonitions);
- the `tally` (done/total, blocked count) and the current phase;
- verbatim config / commands / paths / version pins.

Relay the result as restored context and continue.
