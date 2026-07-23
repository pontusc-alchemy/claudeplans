# Tracer-bullet briefs — host-plans server

Each file is **one bullet** (one INTENDED_GOAL) authored per
`prompt-for-orchestrate-tracer-bullet-approach`: outcome language, no solution
paths, measurable success a verification dispatch can check on this machine.

Consumed by `orchestrate-tracer-bullet-approach`. Verification dispatched to the
`browser-user` sub-agent against the running site on this macOS host.

- `01-html-native-support.md` — HTML documents become first-class discoverable content.
- `02-plans-src-env-var.md` — the served/indexed root is operator-selectable via `PLANS_SRC`.

These two bullets are independent and intentionally NOT bundled. They share one
runtime surface (the MkDocs config dir `~/.config/plans-server`, the served tree,
and the serve port), so they are run **sequentially**, not concurrently.

Server under test: `plugins/plan/server/` (MkDocs Material, Tier-0 macOS path
`make serve` → http://127.0.0.1:8001).
