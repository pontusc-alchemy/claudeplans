---
name: setup
description: Install, upgrade, or repair the local plans rendering stack (MkDocs render unit + Caddy site at http://plans.claude). Run once after installing the plugin, and again after every plugin update.
user-invocable: true
model-invocable: false
allowed-tools: Bash, Read
---

Install the bundled hosting idempotently into the stable runtime dir `~/.config/plans-server/` — the plugin is source + installer; systemd units never point into the plugin cache (its path changes on every update).

## 1 — User-scoped install (no sudo)

```shell
make -C "${CLAUDE_PLUGIN_ROOT}/server" install
```

Renders configs, copies assets, installs the landing-page stub if absent, creates/refreshes the venv, and enables the per-user `plans-render` unit.

On macOS / non-systemd hosts only the portable tier applies: `make install` sets up config + venv, then the user runs `make -C "${CLAUDE_PLUGIN_ROOT}/server" serve` (foreground render at http://127.0.0.1:8001). The render-unit and system-install tiers below are Linux-only.

## 2 — Verify

```shell
make -C "${CLAUDE_PLUGIN_ROOT}/server" status
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" check --all
```

On non-Linux `make status` is unavailable; with `make serve` running, verify the page instead: `curl -fs http://127.0.0.1:8001/index.html | grep -q 'grid cards'`.

Units active, the landing-page probe (`grid cards`) passing, and `check` clean means the stack is healthy.

## 3 — System step (sudo — the user runs it)

If `install`/`status` shows the hint about `http://plans.claude` (the `/etc/hosts` entry + Caddy system unit are missing), tell the user to run it themselves — NEVER run sudo for them:

```shell
make -C "${CLAUDE_PLUGIN_ROOT}/server" system-install
```

## Upgrades

After `/plugin marketplace update plans`, re-run this skill — it re-copies configs and restarts only what changed.
