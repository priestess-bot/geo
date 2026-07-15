SHELL := /bin/bash

DEV_COMPOSE := docker compose -f infra/docker-compose.yml
PROD_ENV ?= infra/production.env
PROD_COMPOSE := docker compose --env-file $(PROD_ENV) -f infra/compose.prod.yml

.PHONY: bootstrap install lint typecheck quality test test-migrated test-integration \
	web-build api-internal api-customer admin-web customer-web \
	db-up db-down db-reset-dev db-migrate db-heads \
	docker-config production-config production-up production-down \
	api-image admin-image customer-image images \
	backup restore-smoke deepseek-live ci

bootstrap: install
	cp -n .env.example .env 2>/dev/null || true

install:
	uv sync --frozen
	corepack pnpm install --frozen-lockfile

lint:
	uv run ruff check apps/api/geo_api packages/geo_core/geo_core

typecheck:
	uv run mypy --follow-imports=skip \
		apps/api/geo_api/app_factory.py \
		apps/api/geo_api/contracts.py \
		apps/api/geo_api/problems.py \
		apps/api/geo_api/stable_routes.py \
		packages/geo_core/geo_core/jobs \
		packages/geo_core/geo_core/engineering \
		packages/geo_core/geo_core/model_gateway \
		packages/geo_core/geo_core/prompts \
		apps/api/geo_api/engineering_runtime.py
	corepack pnpm typecheck

quality: lint typecheck
	uv run pytest -q tests/architecture

test:
	uv run pytest

test-migrated:
	uv run pytest -q \
		tests/architecture \
		tests/unit \
		tests/infra/test_production_compose.py \
		tests/test_api_foundation_contracts.py \
		tests/test_geo_alembic_baseline.py \
		tests/test_geo_job_lifecycle.py \
		tests/test_geo_v3_qc_contracts.py

test-integration:
	@test -n "$$GEO_DATABASE_URL" -o -n "$$DATABASE_URL" || (echo "GEO_DATABASE_URL or DATABASE_URL is required" >&2; exit 2)
	uv run alembic upgrade head
	uv run pytest -q -m integration

web-build:
	corepack pnpm build

api-internal:
	uv run uvicorn geo_api.internal_app:app --app-dir apps/api --reload --port 8000

api-customer:
	uv run uvicorn geo_api.customer_app:app --app-dir apps/api --reload --port 8001

admin-web:
	corepack pnpm --filter geo-production-admin-web dev -- --port 3001

customer-web:
	corepack pnpm --filter geo-production-customer-web dev -- --port 3000

db-up:
	$(DEV_COMPOSE) up -d postgres minio valkey

db-down:
	$(DEV_COMPOSE) down

db-reset-dev:
	@test "$$CONFIRM_DELETE_TEST_DATA" = "1" || (echo "set CONFIRM_DELETE_TEST_DATA=1" >&2; exit 2)
	$(DEV_COMPOSE) down -v
	$(DEV_COMPOSE) up -d postgres minio valkey
	uv run alembic upgrade head

db-migrate:
	uv run alembic upgrade head

db-heads:
	uv run alembic heads

docker-config:
	$(DEV_COMPOSE) config -q

production-config:
	$(PROD_COMPOSE) config -q

production-up: production-config
	$(PROD_COMPOSE) up -d

production-down:
	$(PROD_COMPOSE) down

api-image:
	docker build -f apps/api/Dockerfile -t geo-api:local .

admin-image:
	docker build -f apps/admin-web/Dockerfile -t geo-admin-web:local .

customer-image:
	docker build -f apps/customer-web/Dockerfile -t geo-customer-web:local .

images: api-image admin-image customer-image

backup:
	scripts/backup_geo_data.sh $(PROD_ENV)

restore-smoke:
	@test -n "$$BACKUP_FILE" || (echo "BACKUP_FILE is required" >&2; exit 2)
	scripts/restore_geo_backup_smoke.sh $(PROD_ENV) "$$BACKUP_FILE"

deepseek-live:
	@test -n "$$GEO_DEEPSEEK_API_KEY_FILE" || (echo "GEO_DEEPSEEK_API_KEY_FILE is required" >&2; exit 2)
	uv run pytest -q -m live tests/test_geo_deepseek_live_generation.py

ci: quality test-migrated web-build docker-config
