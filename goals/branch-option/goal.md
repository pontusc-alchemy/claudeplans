# Goal — host-plans: optional branch-level nesting

Add an optional branch level to the host-plans doc tree so docs can live at `projects/<project>/<branch>/<slug>.md` alongside today's flat `projects/<project>/<slug>.md`, detected structurally (a `.md` file is a flat slug; a subdirectory is a branch), capped at one level and never required. This aligns host-plans' topology 1:1 with the visualize tooling's `<repo>/<branch>` convention so generated visualization HTML can be centralized under `PLANS_SRC/projects/<repo>/<branch>/diagrams/` and surfaced on the plans.claude landing page.

- **Shared understanding:** [facts.md](facts.md) — 12 accepted facts (11 automated, 1 manual docs check).
- **Execution plan:** [plan.md](plan.md) — `plan-doc` read/resolve path, `gen_index.py` branch walk + diagram surfacing, docs, fixture-based verification (approved via Plannotator gate).

**Scope:** host-plans only. No write-path (`new --branch`) or `check` validation this round. The `output-dir.py` redirect in the cc-marketplace repo is a separate cross-repo follow-up.

**Done condition:** All 11 automated-verification facts pass their fixture checks; `AUTHORING.md` + `README.md` document the optional branch level, file-vs-dir rule, one-level cap, and reserved `diagrams/` convention; existing flat docs render and resolve unchanged.
