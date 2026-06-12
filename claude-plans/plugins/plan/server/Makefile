# Always-on local plan site — install/config helper (plugin v2).
# Portability tiers: Tier 0 (any OS, no sudo) = config + venv + 'serve' foreground render.
# Tier 1 (Linux/systemd) = 'render-unit' per-user MkDocs serve unit.
# Tier 2 (Linux/systemd, sudo) = 'system-install': Caddy + /etc/hosts for http://plans.claude.
# macOS Tiers 1-2 (launchd/hostname) are designed but not shipped; on macOS use 'make serve'.

SHELL := /bin/bash
.ONESHELL:
.DEFAULT_GOAL := help
.PHONY: help install system-install caddy hosts service venv render-unit serve \
        build restart reload status logs render-status render-logs uninstall

# Self-locating source dir (this Makefile's directory).
SRC           := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
UNAME         := $(shell uname -s)
CONFIG_DIR    := $(HOME)/.config/plans-server
PLANS_DIR     := $(HOME)/plans
PLANS_SRC     := $(PLANS_DIR)/src
UNIT_SRC      := $(CONFIG_DIR)/plans.service
UNIT_DST      := /etc/systemd/system/plans.service
USER_UNIT_DIR := $(HOME)/.config/systemd/user
RENDER_UNIT   := plans-render.service

# Guard for systemd-tier targets; first recipe line of Linux-only entry points.
define require_linux
@[ "$(UNAME)" = "Linux" ] || { echo "Linux-only target (systemd). On macOS: 'make serve' renders at http://127.0.0.1:8001; launchd/hostname tiers are designed but not shipped."; exit 1; }
endef

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: venv ## User-scoped setup (config + venv; render watcher on Linux, no sudo)
	@if [ "$(UNAME)" != "Linux" ]; then \
		echo "Tier 0 complete (config + venv). On macOS: run 'make serve' for the foreground render at http://127.0.0.1:8001; the systemd render/system tiers are Linux-only."; \
		exit 0; \
	fi
	$(MAKE) render-unit
	@if ! grep -qE '^127\.0\.0\.2[[:space:]]+plans\.claude$$' /etc/hosts 2>/dev/null; then \
		echo "Render stack installed. Run 'make system-install' (sudo) for http://plans.claude."; \
	else \
		echo "Done. Open http://plans.claude; write docs to $(PLANS_SRC)/projects/<project>/<slug>.md"; \
	fi

config: ## Render config + copy assets into $(CONFIG_DIR) (idempotent)
	@mkdir -p $(PLANS_SRC)/projects $(PLANS_SRC)/assets $(CONFIG_DIR)
	python3 -c 'import os,sys,string; sys.stdout.write(string.Template(sys.stdin.read()).safe_substitute(HOME=os.environ.get("HOME","")))' < $(SRC)mkdocs.yml.tmpl > $(CONFIG_DIR)/mkdocs.yml
	python3 -c 'import os,sys,string; sys.stdout.write(string.Template(sys.stdin.read()).safe_substitute(HOME=os.environ.get("HOME",""),USER=os.environ.get("USER","")))' < $(SRC)plans.service.tmpl > $(CONFIG_DIR)/plans.service
	cp $(SRC)gen_index.py $(SRC)requirements.txt $(SRC)Caddyfile $(CONFIG_DIR)/
	rm -f $(PLANS_SRC)/assets/extra.css
	cp $(SRC)extra.css $(PLANS_SRC)/assets/extra.css
	@[ -f $(PLANS_SRC)/index.md ] || cp $(SRC)index.md $(PLANS_SRC)/index.md
	@echo "config rendered to $(CONFIG_DIR)"
.PHONY: config

venv: config ## Create/refresh the MkDocs venv + install pinned deps
	@[ -d $(CONFIG_DIR)/venv ] || python3 -m venv $(CONFIG_DIR)/venv
	$(CONFIG_DIR)/venv/bin/pip install --upgrade -r $(CONFIG_DIR)/requirements.txt

serve: venv ## Run the renderer in the foreground (portable; http://127.0.0.1:8001)
	$(CONFIG_DIR)/venv/bin/mkdocs serve -f $(CONFIG_DIR)/mkdocs.yml -a 127.0.0.1:8001

render-unit: ## Install + (re)enable the per-user MkDocs serve unit
	$(require_linux)
	@mkdir -p $(PLANS_SRC)/projects $(USER_UNIT_DIR)
	cp $(SRC)$(RENDER_UNIT) $(USER_UNIT_DIR)/$(RENDER_UNIT)
	systemctl --user daemon-reload
	systemctl --user enable --now plans-render
	systemctl --user restart plans-render
	@echo "mkdocs serve unit enabled; logs: journalctl --user -u plans-render -f"

system-install: caddy hosts service ## Sudo step: /etc/hosts entry + Caddy system unit
	$(require_linux)
	@echo "System site enabled. Open http://plans.claude"

caddy: ## Install Caddy if missing (pacman)
	$(require_linux)
	@if ! command -v caddy >/dev/null 2>&1; then \
		if command -v pacman >/dev/null 2>&1; then \
			sudo pacman -S --needed caddy; \
		else \
			echo "install caddy via your distro's package manager, then re-run"; \
			exit 1; \
		fi; \
	fi

hosts: ## Ensure '127.0.0.2 plans.claude' in /etc/hosts (idempotent, migrates old 'plans')
	$(require_linux)
	@if grep -qE '^127\.0\.0\.2[[:space:]]+plans\.claude$$' /etc/hosts; then \
		echo "/etc/hosts entry already present"; \
	else \
		sudo sed -i -E '/^127\.0\.0\.2[[:space:]]+plans$$/d' /etc/hosts; \
		echo '127.0.0.2  plans.claude' | sudo tee -a /etc/hosts >/dev/null; \
		echo "added '127.0.0.2 plans.claude' to /etc/hosts"; \
	fi

service: config ## Install + enable the Caddy site service (system)
	@mkdir -p $(PLANS_DIR)
	sudo cp $(UNIT_SRC) $(UNIT_DST)
	sudo systemctl daemon-reload
	sudo systemctl enable --now plans
	@echo "service enabled; status: systemctl status plans"

build: ## One-off static build of the site to ~/plans/site
	@$(CONFIG_DIR)/venv/bin/mkdocs build -f $(CONFIG_DIR)/mkdocs.yml

restart: ## Restart the plan site service
	$(require_linux)
	sudo systemctl restart plans

reload: ## Reload Caddy config (falls back to restart if needed)
	$(require_linux)
	sudo systemctl reload plans || sudo systemctl restart plans

status: ## Show render + site status and probe the landing page
	$(require_linux)
	@systemctl --user is-active plans-render || true
	-systemctl status plans --no-pager
	@curl -fs http://127.0.0.2:8001/index.html | grep -q 'grid cards' \
		&& echo "landing page OK (grid cards present)" \
		|| echo "landing page probe FAILED"

logs: ## Follow site service logs
	$(require_linux)
	journalctl -u plans -f

render-status: ## Show render watcher status
	$(require_linux)
	systemctl --user status plans-render --no-pager

render-logs: ## Follow render watcher logs
	$(require_linux)
	journalctl --user -u plans-render -f

uninstall: ## Stop + remove services and /etc/hosts entry
	$(require_linux)
	-systemctl --user disable --now plans-render
	-rm -f $(USER_UNIT_DIR)/$(RENDER_UNIT)
	systemctl --user daemon-reload
	-sudo systemctl disable --now plans
	-sudo rm -f $(UNIT_DST)
	sudo systemctl daemon-reload
	-sudo sed -i -E '/^127\.0\.0\.2[[:space:]]+plans(\.claude)?$$/d' /etc/hosts
	@echo "uninstalled (note: ~/plans, $(CONFIG_DIR), and packages are left intact)"
