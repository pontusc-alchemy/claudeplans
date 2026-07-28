# claudeplans — dev inner loop + Docker Bake jobs. (Make requires real tabs.)
.PHONY: help venv check lint fmt typecheck test bake-ci ci serve-build serve up down seed

UV ?= uv

help: ## Show this help.
	@grep -E '^[a-zA-Z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*##"}; {printf "  %-14s %s\n", $$1, $$2}'

venv: ## Create/refresh the local uv venv (all members, for editor + ty LSP).
	$(UV) sync --all-packages

lint: venv ## Ruff lint.
	$(UV) run ruff check packages tests scripts

fmt: venv ## Ruff format (writes).
	$(UV) run ruff format packages tests scripts

typecheck: venv ## ty type check.
	$(UV) run ty check packages tests scripts

test: venv ## Pytest suite.
	$(UV) run pytest

check: venv ## Full local quality gate (matches scripts/ci.sh).
	$(UV) run ruff check packages tests scripts
	$(UV) run ruff format --check packages tests scripts
	$(UV) run ty check packages tests scripts
	$(UV) run pytest

bake-ci: ## Build the ci image.
	docker buildx bake ci

ci: bake-ci ## Run the gate in the ci image against mounted source.
	docker run --rm -v "$(CURDIR)":/work claudeplans:ci

serve-build: ## Build the bare serve image.
	docker buildx bake serve

serve: ## Bring up the stable stack (project claudeplans; run from the pinned release worktree).
	docker compose -p claudeplans up --build -d

up: ## Build + run the dev stack (default project claudeplans-dev) on 127.0.0.1:9394; waits for healthy.
	CLAUDEPLANS_HOST_IP=127.0.0.1 CLAUDEPLANS_HOST_PORT=9394 docker compose up --build -d --wait

down: ## Stop the dev stack (volumes kept; wipe: docker compose down -v).
	docker compose down

seed: venv $(if $(CLAUDEPLANS_URL),,up) ## Seed demo projects — brings the dev stack up, unless CLAUDEPLANS_URL targets elsewhere.
	$(UV) run python scripts/seed.py
