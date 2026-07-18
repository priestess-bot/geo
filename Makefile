SHELL := /bin/bash

DEV_COMPOSE := docker compose -f infra/docker-compose.yml
PROD_ENV ?= infra/production.env
PROD_COMPOSE := docker compose --env-file $(PROD_ENV) -f infra/compose.prod.yml

.PHONY: bootstrap install lint python-typecheck web-typecheck typecheck quality test test-migrated test-integration \
	openapi-snapshots openapi-contracts \
	web-build api-internal api-customer admin-web customer-web \
	dev-up dev-logs dev-down db-up db-down db-reset-dev db-migrate db-heads \
	docker-config production-config production-up production-down \
	production-provision-owner \
	api-image admin-image customer-image images \
	backup restore-smoke backup-restore-dev-smoke deepseek-live ci \
	advinsys-dry-run advinsys-verify operator-guide-pdf

bootstrap: install
	cp -n .env.example .env 2>/dev/null || true

install:
	uv sync --frozen
	corepack pnpm install --frozen-lockfile

lint:
	uv run ruff check apps/api/geo_api packages/geo_core/geo_core \
		scripts/export_stable_openapi.py scripts/provision_database.py \
		scripts/provision_dev_database.py scripts/provision_initial_owner.py \
		infra/db/alembic/checksums.py

python-typecheck:
	uv run mypy --follow-imports=skip \
		apps/api/geo_api \
		apps/api/geo_worker \
		packages/geo_core/geo_core \
		scripts/export_stable_openapi.py \
		scripts/provision_database.py \
		scripts/provision_dev_database.py \
		scripts/provision_initial_owner.py

web-typecheck:
	corepack pnpm typecheck

typecheck: python-typecheck web-typecheck

quality: lint typecheck
	uv run pytest -q tests/architecture

test:
	uv run pytest

test-migrated:
	uv run pytest -q -m "not integration and not live and not browser"

openapi-snapshots:
	uv run python scripts/export_stable_openapi.py export

openapi-contracts:
	uv run python scripts/export_stable_openapi.py verify
	uv run pytest -q tests/test_stable_openapi_contracts.py

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

production-provision-owner: production-config
	$(PROD_COMPOSE) --profile provisioning run --rm initial-owner-provision

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

backup-restore-dev-smoke:
	scripts/backup_restore_development_smoke.sh

deepseek-live:
	@test -n "$$GEO_DEEPSEEK_API_KEY_FILE" || (echo "GEO_DEEPSEEK_API_KEY_FILE is required" >&2; exit 2)
	uv run pytest -q -m live tests/test_geo_deepseek_live_generation.py

advinsys-dry-run:
	uv run python scripts/provision_advinsys_project.py --mode actual --dry-run

advinsys-verify:
	uv run python scripts/provision_advinsys_project.py --mode actual --verify-only

operator-guide-pdf:
	uv run python scripts/render_geo_operator_guide.py

ci: quality test-migrated openapi-contracts web-build docker-config

dev-up:
	@test -f "$(CURDIR)/deepseek_api_key.txt" || (echo "deepseek_api_key.txt is required" >&2; exit 2)
	@test "$$(stat -c '%a' "$(CURDIR)/deepseek_api_key.txt")" = "600" -o \
		"$$(stat -c '%a' "$(CURDIR)/deepseek_api_key.txt")" = "400" || \
		(echo "deepseek_api_key.txt must use mode 0400 or 0600" >&2; exit 2)
	GEO_DEV_HOST_UID="$$(id -u)" GEO_DEV_HOST_GID="$$(id -g)" \
		GEO_DEEPSEEK_API_KEY_FILE="$(CURDIR)/deepseek_api_key.txt" \
		$(DEV_COMPOSE) --profile workers up -d --build --wait

dev-logs:
	$(DEV_COMPOSE) --profile workers logs -f --tail=200

dev-down:
	$(DEV_COMPOSE) --profile workers down
