SHELL := /bin/bash

DEV_COMPOSE := docker compose -f infra/docker-compose.yml
PROD_ENV ?= infra/production.env
PROD_COMPOSE := docker compose --env-file $(PROD_ENV) -f infra/compose.prod.yml -f infra/compose.style-collection.yml

.PHONY: bootstrap install lint python-typecheck web-typecheck typecheck quality test test-migrated test-integration test-integration-required \
	roadmap-evidence-schema roadmap-evidence-verify roadmap-performance-profile \
	non-b-acceptance-register non-b-acceptance-register-verify \
	model-gateway-runtime-schema model-gateway-runtime-template \
	model-gateway-runtime-verify model-gateway-runtime-register \
	roadmap-performance-workload \
	roadmap-migration-cutover-schema roadmap-migration-cutover-verify \
	roadmap-migration-cutover-rehearsal \
	roadmap-performance-api-load \
	roadmap-performance-api-load-verify \
	roadmap-non-b-fault-contracts roadmap-non-b-fault-runtime \
	roadmap-non-b-fault-receipt-verify \
	roadmap-performance-result-schema roadmap-performance-result-verify \
	scan-backup-plaintext scan-repository-secrets \
	openapi-snapshots openapi-contracts \
	web-contracts web-build test-browser-chromium geo-acceptance-inline geo-staging-smoke \
	test-infra-contracts test-infra-runtime api-internal api-customer admin-web customer-web \
	dev-up dev-logs dev-down db-up db-down db-reset-dev db-migrate db-heads \
	docker-config production-preflight production-config production-up production-down \
	test-production-network \
	production-provision-owner \
	api-image admin-image customer-image images \
	backup restore-smoke backup-restore-dev-smoke deepseek-live ci \
	advinsys-dry-run advinsys-verify f019-benchmark operator-guide-pdf

bootstrap: install
	cp -n .env.example .env 2>/dev/null || true

install:
	uv sync --frozen
	corepack pnpm install --frozen-lockfile

lint:
	uv run ruff check apps/api/geo_api apps/api/geo_worker packages/geo_core/geo_core \
		scripts/export_stable_openapi.py scripts/provision_database.py \
		scripts/alembic_sql_ledger.py \
		scripts/backup_envelope.py scripts/backup_manifest.py \
		scripts/backup_restore_gate_seed*.py \
		scripts/scan_backup_plaintext_artifacts.py \
		scripts/scan_repository_secrets.py \
		scripts/verify_minio_backup.py scripts/write_backup_restore_receipt.py \
		scripts/write_restore_acl_rls_canary.py \
		scripts/provision_dev_database.py scripts/provision_initial_owner.py \
		scripts/production_preflight*.py scripts/geo_staging_smoke.py \
		scripts/run_infra_runtime_tests.py scripts/verify_geo_acceptance_report.py \
		scripts/roadmap_evidence_manifest.py \
		scripts/non_b_roadmap_acceptance.py \
		scripts/roadmap_performance_profile.py \
		scripts/roadmap_performance_workload.py \
		scripts/roadmap_migration_cutover.py \
		scripts/run_roadmap_api_load.py \
		scripts/roadmap_performance_api_load.py \
		scripts/run_non_b_fault_contracts.py \
		scripts/roadmap_performance_result.py \
		infra/db/alembic/checksums.py

python-typecheck:
	uv run mypy --follow-imports=skip \
		apps/api/geo_api \
		apps/api/geo_worker \
		packages/geo_core/geo_core \
		scripts/backup_envelope.py \
		scripts/alembic_sql_ledger.py \
		scripts/backup_manifest.py \
		scripts/backup_restore_gate_seed*.py \
		scripts/scan_backup_plaintext_artifacts.py \
		scripts/scan_repository_secrets.py \
		scripts/verify_minio_backup.py \
		scripts/write_backup_restore_receipt.py \
		scripts/write_restore_acl_rls_canary.py \
		scripts/provision_database.py \
		scripts/provision_dev_database.py \
		scripts/provision_initial_owner.py \
		scripts/production_preflight*.py \
		scripts/geo_staging_smoke.py \
		scripts/run_infra_runtime_tests.py \
		scripts/verify_geo_acceptance_report.py \
		scripts/roadmap_evidence_manifest.py \
		scripts/non_b_roadmap_acceptance.py \
		scripts/roadmap_performance_profile.py \
		scripts/roadmap_performance_workload.py \
		scripts/roadmap_migration_cutover.py \
		scripts/run_roadmap_api_load.py \
		scripts/roadmap_performance_api_load.py \
		scripts/run_non_b_fault_contracts.py \
		scripts/roadmap_performance_result.py

web-typecheck:
	corepack pnpm typecheck

typecheck: python-typecheck web-typecheck

quality: lint typecheck scan-backup-plaintext scan-repository-secrets
	uv run pytest -q tests/architecture

test:
	uv run pytest

test-migrated:
	uv run pytest -q --strict-markers --fail-on-skipped \
		--ci-summary-label="Required non-live test suite" \
		-m "not integration and not live and not browser"

roadmap-evidence-schema:
	uv run python scripts/roadmap_evidence_manifest.py export-schema \
		contracts/roadmap/roadmap-evidence-manifest-v1.schema.json

roadmap-evidence-verify:
	@test -n "$$MANIFEST" || (echo "MANIFEST is required" >&2; exit 2)
	uv run python scripts/roadmap_evidence_manifest.py verify "$$MANIFEST"

non-b-acceptance-register:
	uv run python scripts/non_b_roadmap_acceptance.py export

non-b-acceptance-register-verify:
	uv run python scripts/non_b_roadmap_acceptance.py verify

model-gateway-runtime-schema:
	uv run python scripts/model_gateway_runtime_manifest.py export-schema \
		--output contracts/roadmap/model-gateway-runtime-manifest-v2.schema.json

model-gateway-runtime-template:
	uv run python scripts/model_gateway_runtime_manifest.py export-template \
		--output contracts/roadmap/model-gateway-runtime-manifest-six-provider.template.json

model-gateway-runtime-verify:
	@test -n "$$MANIFEST" || (echo "MANIFEST is required" >&2; exit 2)
	uv run python scripts/model_gateway_runtime_manifest.py verify \
		--manifest "$$MANIFEST" --require-six-providers

model-gateway-runtime-register:
	@test -n "$$MANIFEST" || (echo "MANIFEST is required" >&2; exit 2)
	uv run python scripts/model_gateway_runtime_manifest.py register \
		--manifest "$$MANIFEST" --require-six-providers

roadmap-performance-profile:
	uv run python scripts/roadmap_performance_profile.py export \
		benchmarks/roadmap/performance-profile-v1-non-b.json

roadmap-performance-workload:
	uv run python scripts/roadmap_performance_workload.py export \
		benchmarks/roadmap/performance-workload-v1-non-b.json

roadmap-migration-cutover-schema:
	uv run python scripts/roadmap_migration_cutover.py export-schema \
		contracts/roadmap/migration-cutover-receipt-v1.schema.json

roadmap-migration-cutover-verify:
	@test -n "$$RECEIPT" || (echo "RECEIPT is required" >&2; exit 2)
	uv run python scripts/roadmap_migration_cutover.py verify "$$RECEIPT"

roadmap-migration-cutover-rehearsal:
	@test -n "$$GEO_MIGRATION_REHEARSAL_DATABASE_URL" || \
		(echo "GEO_MIGRATION_REHEARSAL_DATABASE_URL is required" >&2; exit 2)
	@test -n "$$OUTPUT" || (echo "OUTPUT is required" >&2; exit 2)
	uv run python scripts/roadmap_migration_cutover.py run \
		--output "$$OUTPUT" --confirm-isolated-database

roadmap-performance-api-load:
	@test -n "$(PERF_ARGS)" || (echo "PERF_ARGS is required" >&2; exit 2)
	uv run python scripts/run_roadmap_api_load.py $(PERF_ARGS)

roadmap-performance-api-load-verify:
	@test -n "$(PERF_API_REPORT_ARGS)" || (echo "PERF_API_REPORT_ARGS is required" >&2; exit 2)
	uv run python scripts/roadmap_performance_api_load.py $(PERF_API_REPORT_ARGS)

roadmap-non-b-fault-contracts:
	uv run python scripts/run_non_b_fault_contracts.py --execute

roadmap-non-b-fault-runtime:
	@test -n "$$GEO_MIGRATION_REHEARSAL_DATABASE_URL" || \
		(echo "GEO_MIGRATION_REHEARSAL_DATABASE_URL is required" >&2; exit 2)
	@test -n "$$GEO_PLACEMENT_TEST_ADMIN_URL" || \
		(echo "GEO_PLACEMENT_TEST_ADMIN_URL is required" >&2; exit 2)
	@test -n "$$FAULT_RECEIPT" || (echo "FAULT_RECEIPT is required" >&2; exit 2)
	uv run python scripts/run_non_b_fault_contracts.py --execute \
		--include-isolated-runtime --receipt "$$FAULT_RECEIPT"

roadmap-non-b-fault-receipt-verify:
	@test -n "$$FAULT_RECEIPT" || (echo "FAULT_RECEIPT is required" >&2; exit 2)
	uv run python scripts/run_non_b_fault_contracts.py \
		--verify-receipt "$$FAULT_RECEIPT"

roadmap-performance-result-verify:
	@test -n "$$RESULT" || (echo "RESULT is required" >&2; exit 2)
	uv run python scripts/roadmap_performance_result.py verify "$$RESULT"

roadmap-performance-result-schema:
	uv run python scripts/roadmap_performance_result.py export-schema \
		contracts/roadmap/performance-result-v1.schema.json

scan-backup-plaintext:
	@if test -d artifacts; then \
		uv run python scripts/scan_backup_plaintext_artifacts.py \
			--allow-disclosed-legacy artifacts; \
	else \
		echo "OK code=BACKUP_PLAINTEXT_SCAN_PASSED artifacts_directory=absent"; \
	fi

scan-repository-secrets:
	uv run python scripts/scan_repository_secrets.py

openapi-snapshots:
	uv run python scripts/export_stable_openapi.py export

openapi-contracts:
	uv run python scripts/export_stable_openapi.py verify
	uv run pytest -q tests/test_stable_openapi_contracts.py

web-contracts:
	corepack pnpm test:contracts

test-integration: test-integration-required

test-integration-required:
	@missing=0; \
	for name in GEO_DATABASE_URL \
		GEO_ACCESS_TEST_ADMIN_DATABASE_URL GEO_ACCESS_TEST_DATABASE_URL \
		GEO_ACCEPTANCE_TEST_ADMIN_DATABASE_URL GEO_ACCEPTANCE_TEST_APP_DATABASE_URL \
		GEO_ACCEPTANCE_TEST_ISOLATION_MARKER GEO_ACCEPTANCE_TEST_WORKER_DATABASE_URL \
		GEO_PLACEMENT_TEST_ADMIN_URL \
		GEO_F019_TEST_MINIO_ENDPOINT \
		GEO_TEST_DATABASE_URL; do \
		if test -z "$${!name:-}"; then echo "$$name is required" >&2; missing=1; fi; \
	done; \
	test "$$missing" -eq 0
	uv run alembic upgrade head
	uv run pytest -q --strict-markers --fail-on-skipped \
		--ci-summary-label="PostgreSQL integration" -m integration \
		tests/integration tests/test_engineering_governance_postgres.py

web-build:
	corepack pnpm build

test-browser-chromium:
	corepack pnpm test:browser:chromium

geo-acceptance-inline:
	@missing=0; \
	for name in GEO_ACCEPTANCE_APP_DATABASE_URL GEO_ACCEPTANCE_WORKER_DATABASE_URL \
		GEO_ACCEPTANCE_ADMIN_DATABASE_URL GEO_ACCEPTANCE_ISOLATION_MARKER; do \
		if test -z "$${!name:-}"; then echo "$$name is required" >&2; missing=1; fi; \
	done; \
	test "$$missing" -eq 0
	@output="$${GEO_ACCEPTANCE_OUTPUT:-artifacts/geo-acceptance/inline-result.json}"; \
	run_id="$${GEO_ACCEPTANCE_RUN_ID:-geo-inline-$$(date -u +%Y%m%d%H%M%S)-$$$$}"; \
	uv run python scripts/run_geo_acceptance.py \
		--environment "$${GEO_ACCEPTANCE_ENVIRONMENT:-test}" \
		--confirm-controlled-simulation --run-id "$$run_id" --output "$$output"; \
	uv run python scripts/verify_geo_acceptance_report.py "$$output"

test-infra-contracts:
	uv run pytest -q --strict-markers --fail-on-skipped \
		--ci-summary-label="Infrastructure contracts" \
		tests/infra/test_development_compose.py \
		tests/infra/test_authenticated_backup_scripts.py \
		tests/infra/test_production_compose.py \
		tests/infra/test_production_preflight.py

test-infra-runtime:
	uv run python scripts/run_infra_runtime_tests.py

geo-staging-smoke:
	@test "$$GEO_RUN_STAGING_SMOKE" = "1" || \
		(echo "Staging external smoke was not authorized; set GEO_RUN_STAGING_SMOKE=1 to opt in" >&2; exit 2)
	@test "$$GEO_CONFIRM_STAGING_PAID_MODEL_CALL" = "1" || \
		(echo "Paid staging model call was not authorized; set GEO_CONFIRM_STAGING_PAID_MODEL_CALL=1" >&2; exit 2)
	@uv run python scripts/geo_staging_smoke.py \
		--confirm-external-smoke --confirm-paid-model-call

test-production-network:
	uv run pytest -q --strict-markers --fail-on-skipped \
		--ci-summary-label="Production network isolation" -m integration \
		tests/infra/test_production_network_runtime.py

f019-benchmark:
	uv run python -m benchmarks.f019.cli validate
	uv run python -m benchmarks.f019.cli run --adapter deterministic \
		--output /tmp/f019-baseline-reference.json
	uv run python -m benchmarks.f019.cli verify-selection

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

production-preflight:
	uv run python scripts/production_preflight.py --env-file $(PROD_ENV)

production-config: production-preflight
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

backup: production-preflight
	scripts/backup_geo_data.sh $(PROD_ENV)

restore-smoke: production-preflight
	@test -n "$${BACKUP_DIR:-$${BACKUP_FILE:-}}" || \
		(echo "BACKUP_DIR (or legacy BACKUP_FILE pointing to a directory) is required" >&2; exit 2)
	scripts/restore_geo_backup_smoke.sh $(PROD_ENV) "$${BACKUP_DIR:-$$BACKUP_FILE}"

backup-restore-dev-smoke:
	scripts/run_authenticated_restore_gate.sh

deepseek-live:
	@test "$$GEO_RUN_LIVE_DEEPSEEK_TEST" = "1" || \
		(echo "Paid DeepSeek call was not requested; set GEO_RUN_LIVE_DEEPSEEK_TEST=1 to opt in" >&2; exit 2)
	@test -n "$$GEO_DEEPSEEK_API_KEY_FILE" || (echo "GEO_DEEPSEEK_API_KEY_FILE is required" >&2; exit 2)
	uv run pytest -q --strict-markers --fail-on-skipped \
		--ci-summary-label="DeepSeek live" -m live tests/test_geo_deepseek_live_generation.py

advinsys-dry-run:
	uv run python scripts/provision_advinsys_project.py --mode actual --dry-run

advinsys-verify:
	uv run python scripts/provision_advinsys_project.py --mode actual --verify-only

operator-guide-pdf:
	uv run python scripts/render_geo_operator_guide.py

ci: quality test-migrated openapi-contracts web-contracts web-build docker-config

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
