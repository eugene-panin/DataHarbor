.PHONY: help dev down clean install dagster compose-up compose-down validate-bundles check

help:
	@echo "Available commands:"
	@echo "  make check        - Same checks as CI (ruff + pytest + validate + build)"
	@echo "  make dev          - Run project in local Kubernetes via Tilt"
	@echo "  make down         - Stop local Kubernetes resources via Tilt"
	@echo "  make compose-up   - Start full stack locally via Docker Compose"
	@echo "  make compose-down - Stop Docker Compose stack"
	@echo "  make validate-bundles - Validate all bundles in bundles/ directory"
	@echo "  make install      - Install Python dependencies locally (uv)"
	@echo "  make dagster      - Run Dagster webserver locally (http://localhost:3000)"
	@echo "  make clean        - Clean temporary Python files"

install:
	uv sync

dev:
	tilt up --file Tiltfile

down:
	tilt down --file Tiltfile

compose-up:
	cp -n .env.example .env || true
	docker compose up --build -d

compose-down:
	docker compose down

validate-bundles:
	uv run harbor bundle validate

check:
	uv run ruff check apps bundles extractors tests
	PYTHONPATH=. uv run pytest tests/ -q --tb=short
	PYTHONPATH=. uv run harbor bundle validate
	PYTHONPATH=. uv run harbor extractor validate
	uv build

dagster:
	mkdir -p /tmp/dagster_home && uv run python -m apps.dagster_app.run_dev

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
