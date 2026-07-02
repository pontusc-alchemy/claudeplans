# claudeplans — dev inner loop + Docker Bake jobs. (Make requires real tabs.)
.PHONY: venv check lint fmt typecheck test bake-ci ci serve-build serve up down seed

UV ?= uv

venv: ## Create/refresh the local uv venv (all members, for editor + ty LSP).
	$(UV) sync --all-packages

lint:
	$(UV) run ruff check packages tests

fmt:
	$(UV) run ruff format packages tests

typecheck:
	$(UV) run ty check packages tests

test:
	$(UV) run pytest

check: ## Full local quality gate (matches scripts/ci.sh).
	$(UV) run ruff check packages tests
	$(UV) run ruff format --check packages tests
	$(UV) run ty check packages tests
	$(UV) run pytest

bake-ci: ## Build the ci image.
	docker buildx bake ci

ci: bake-ci  ## Run the gate in the ci image against mounted source.
	docker run --rm -v "$(CURDIR)":/work claudeplans:ci

serve-build: ## Build the bare serve image.
	docker buildx bake serve

serve: ## Bring up the stable stack (project claudeplans; run from the pinned release worktree).
	docker compose -p claudeplans up --build -d

up: ## Build + run the dev stack (default project claudeplans-dev) on 127.0.0.1:9394.
	CLAUDEPLANS_HOST_IP=127.0.0.1 CLAUDEPLANS_HOST_PORT=9394 docker compose up --build -d

down: ## Stop the dev stack (volumes kept; wipe: docker compose down -v).
	docker compose down

seed: ## Seed demo projects into the dev stack (override: CLAUDEPLANS_URL=...).
	$(UV) run python scripts/seed.py
