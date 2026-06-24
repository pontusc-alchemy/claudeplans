# claudeplans — dev inner loop + Docker Bake jobs. (Make requires real tabs.)
.PHONY: venv check lint fmt typecheck test bake-ci ci serve-build serve up down

UV ?= uv

venv:  ## Create/refresh the local uv venv (all members, for editor + ty LSP).
	$(UV) sync --all-packages

lint:
	$(UV) run ruff check packages tests

fmt:
	$(UV) run ruff format packages tests

typecheck:
	$(UV) run ty check packages tests

test:
	$(UV) run pytest

check:  ## Full local quality gate (matches scripts/ci.sh).
	$(UV) run ruff check packages tests
	$(UV) run ruff format --check packages tests
	$(UV) run ty check packages tests
	$(UV) run pytest

bake-ci:  ## Build the ci image.
	docker buildx bake ci

ci: bake-ci  ## Run the gate in the ci image against mounted source.
	docker run --rm -v "$(CURDIR)":/work claudeplans:ci

serve-build:  ## Build the bare serve image.
	docker buildx bake serve

serve:  ## Run the bare serve image locally on :8000.
	docker run --rm -p 8000:8000 claudeplans:serve

up:  ## Build + run the local stack (compose, filesystem + noop auth) on :8000.
	docker compose up --build

down:  ## Stop the local stack (the data volume is kept; add -v to wipe).
	docker compose down
