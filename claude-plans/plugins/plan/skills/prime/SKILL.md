---
name: prime
description: Bootstrap session context from a saved plans document or project. Given a project name, enumerate its docs and brief from the active ones; given a slug, brief that document. Delegates the reading to a Haiku agent.
user-invocable: true
model-invocable: true
allowed-tools: Bash, Agent
model: haiku
---

Load context from a saved document under `~/plans/src/projects/` by delegating the reads to a Haiku agent — never read large files in the main thread. The argument is a project name or a slug.

## Resolve the source

- **Project name** (a dir under `~/plans/src/projects/`): list its docs (`ls ~/plans/src/projects/<project>/*.md`). Brief from the `status: active` ones. If several are active, brief all; if none are, list them and ask. Don't guess.
- **Slug:** match against `~/plans/src/projects/*/*.md`. No clear single match → `ls ~/plans/src/projects/*/*.md` and ask.

## Brief (delegate, haiku)

Spawn one `Agent` (`general-purpose`, `haiku`) to read the resolved doc(s) and return a DENSE briefing:

- title + intro; section list (level-2 `##`) in order;
- locked decisions (`<span class="pill ok">`);
- open gaps/caveats (`pill gap` / `pill partial` spans, `!!! warning` / `!!! danger` admonitions);
- for `type: plan`: the **current phase** (first phase whose pill is not `ok`) and its **unchecked `- [ ]` tasks**;
- verbatim config / commands / paths / version pins.

Relay the result as restored context and continue.
