# Developer entry points. Everything here is also runnable directly with
# `uv run ...` — the Makefile only names the common combinations.

.PHONY: install lint format typecheck test cov check smoke-test

install:
	uv sync
	uv run pre-commit install || true

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest

cov:
	uv run pytest --cov --cov-report=term-missing

# Everything CI runs, in CI order. Run before pushing.
check: lint typecheck cov

# Manual-only: talks to the CIS demo environment. Requires FINA demo
# certificates configured locally. Never runs in CI. (Arrives in Phase 1.)
smoke-test:
	uv run pytest -m demo
