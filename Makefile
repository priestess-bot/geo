.PHONY: install-api-deps install-dev-deps lint-python compile-python web-typecheck quality test web-build docker-config docker-config-llm docker-config-scheduler docker-config-observability docker-config-db-smoke db-smoke runtime-e2e ci-local api-preflight verify-api-preflight preflight-manifest au-p0a-runbook verify-au-p0a-runbook au-p0a-env verify-au-p0a-env au-p0a-runbook-dry-run verify-au-p0a-runbook-execution au-p0a-readiness au-p0a-package verify-au-p0a-package au-p0a-status verify-au-p0a-status au-p0b-google-runbook verify-au-p0b-google-runbook au-p0b-google-runbook-dry-run verify-au-p0b-google-runbook-execution au-p0b-google-status verify-au-p0b-google-status au-p0b-google-manual-template verify-au-p0b-google-manual-backfill au-p0b-google-playwright-env verify-au-p0b-google-playwright-env au-p0b-google-playwright-smoke verify-au-p0b-google-playwright-smoke au-p0b-google-serp-health verify-au-p0b-google-serp-health au-p0b-google-serp-health-manifest au-p0b-google-serp-fixture verify-au-p0b-google-serp-fixture au-p0b-google-serp-fixture-manifest au-p0b-google-serp-status verify-au-p0b-google-serp-status browser-fidelity-plan browser-fidelity-scheduler-plan browser-fidelity-scheduler-run api-browser-fidelity-preflight report-export-worker runtime-alert-notification-worker runtime-alert-escalation-worker notification-delivery-worker worker-fixture worker-fixture-persist worker-google-fixture

install-api-deps:
	python3 -m pip install -r apps/api/requirements.txt

install-dev-deps:
	python3 -m pip install -r requirements-dev.txt

lint-python:
	python3 -m ruff check apps/api packages workers scripts tests

compile-python:
	python3 -m compileall apps/api/geno_api packages/geno_core/geno_core workers scripts tests

web-typecheck:
	npm --prefix apps/web run typecheck

quality: lint-python compile-python web-typecheck

test:
	PYTHONPATH=packages/geno_core:apps/api python3 -m unittest discover -s tests

web-build:
	npm --prefix apps/web run build

docker-config:
	docker compose -f infra/docker-compose.yml config

docker-config-llm:
	docker compose -f infra/docker-compose.yml --profile llm-gateway config

docker-config-scheduler:
	docker compose -f infra/docker-compose.yml --profile scheduler config

docker-config-observability:
	docker compose -f infra/docker-compose.yml --profile observability config

docker-config-db-smoke:
	docker compose -f infra/docker-compose.yml --profile db-smoke config

db-smoke:
	set -e; \
	trap 'docker compose -p geno-db-smoke -f infra/docker-compose.yml --profile db-smoke down -v' EXIT; \
	docker compose -p geno-db-smoke -f infra/docker-compose.yml --profile db-smoke build db-smoke; \
	docker compose -p geno-db-smoke -f infra/docker-compose.yml --profile db-smoke run --rm db-smoke

runtime-e2e:
	set -e; \
	trap 'docker compose -p geno-runtime-e2e -f infra/docker-compose.yml --profile e2e down -v' EXIT; \
	docker compose -p geno-runtime-e2e -f infra/docker-compose.yml --profile e2e build runtime-e2e; \
	docker compose -p geno-runtime-e2e -f infra/docker-compose.yml --profile e2e run --rm runtime-e2e

ci-local: quality test web-build docker-config docker-config-llm docker-config-scheduler docker-config-observability docker-config-db-smoke db-smoke runtime-e2e

api-preflight:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode api --prompt-limit 1 --cities Sydney --sample-size 3 --require-ready-collectors --require-p0a-readiness --preflight-output-path $${GENO_API_PREFLIGHT_OUTPUT_PATH:-docs/runtime_preflight/api-preflight-latest.json}

verify-api-preflight:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_preflight_payload.py $${GENO_API_PREFLIGHT_OUTPUT_PATH:-docs/runtime_preflight/api-preflight-latest.json}

preflight-manifest:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_preflight_manifest.py $${GENO_API_PREFLIGHT_OUTPUT_PATH:-docs/runtime_preflight/api-preflight-latest.json} --manifest-path $${GENO_API_PREFLIGHT_MANIFEST_PATH:-docs/runtime_preflight/api-preflight-manifest-latest.json}

au-p0a-runbook:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0a_runbook.py --output-path $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json}

verify-au-p0a-runbook:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_runbook.py $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json}

au-p0a-env:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0a_env_report.py --runbook-path $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json} --env-file $${GENO_AU_P0A_ENV_FILE:-.env.au-p0a} --output-path $${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json}

verify-au-p0a-env:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_env_report.py $${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json}

au-p0a-runbook-dry-run:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/run_au_p0a_runbook.py --runbook-path $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json} --output-path $${GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-execution-latest.json}

verify-au-p0a-runbook-execution:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_runbook_execution.py $${GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-execution-latest.json}

au-p0a-readiness:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_readiness.py --phase $${GENO_AU_P0A_READINESS_PHASE:-preflight} --runbook-path $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json} --output-path $${GENO_AU_P0A_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-readiness-latest.json}

au-p0a-package:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0a_evidence_package.py --runbook-path $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json} --environment-path $${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} --readiness-path $${GENO_AU_P0A_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-readiness-latest.json} --runbook-execution-path $${GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-execution-latest.json} --output-path $${GENO_AU_P0A_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-evidence-package-latest.json}

verify-au-p0a-package:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_evidence_package.py $${GENO_AU_P0A_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-evidence-package-latest.json}

au-p0a-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0a_status_report.py --runbook-path $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json} --environment-path $${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} --readiness-path $${GENO_AU_P0A_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-readiness-latest.json} --runbook-execution-path $${GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-execution-latest.json} --package-path $${GENO_AU_P0A_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-evidence-package-latest.json} --output-path $${GENO_AU_P0A_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-status-latest.json}

verify-au-p0a-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_status_report.py $${GENO_AU_P0A_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-status-latest.json}

au-p0b-google-runbook:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_spike_runbook.py --output-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json}

verify-au-p0b-google-runbook:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_spike_runbook.py $${GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json}

au-p0b-google-runbook-dry-run:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/run_au_p0b_google_spike_runbook.py --runbook-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json} --output-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-execution-latest.json}

verify-au-p0b-google-runbook-execution:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_spike_runbook_execution.py $${GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-execution-latest.json}

au-p0b-google-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_spike_status_report.py --runbook-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json} --execution-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-execution-latest.json} --output-path $${GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-status-latest.json}

verify-au-p0b-google-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_spike_status_report.py $${GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-status-latest.json}

au-p0b-google-manual-template:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_manual_backfill_template.py --output-path $${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_TEMPLATE_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-template.jsonl} --manifest-path $${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_TEMPLATE_MANIFEST_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-template-manifest.json}

verify-au-p0b-google-manual-backfill:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_manual_backfill.py $${MANUAL_BACKFILL_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-template.jsonl} --output-path $${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_VERIFICATION_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json}

au-p0b-google-playwright-env:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_playwright_env_report.py --runbook-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json} --env-file $${GENO_AU_P0B_GOOGLE_ENV_FILE:-.env.au-p0b-google} --output-path $${GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-env-latest.json}

verify-au-p0b-google-playwright-env:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_playwright_env_report.py $${GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-env-latest.json}

au-p0b-google-playwright-smoke:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/run_au_p0b_google_playwright_smoke.py --output-path $${GENO_AU_P0B_GOOGLE_PLAYWRIGHT_SMOKE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json}

verify-au-p0b-google-playwright-smoke:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_playwright_smoke.py $${GENO_AU_P0B_GOOGLE_PLAYWRIGHT_SMOKE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json}

au-p0b-google-serp-health:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode google-serp-spike --require-ready-collectors --health-check-only --preflight-output-path $${GENO_AU_P0B_GOOGLE_SERP_HEALTH_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-serp-health-latest.json}

verify-au-p0b-google-serp-health:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_serp_comparison.py $${GENO_AU_P0B_GOOGLE_SERP_HEALTH_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-serp-health-latest.json}

au-p0b-google-serp-health-manifest:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_preflight_manifest.py $${GENO_AU_P0B_GOOGLE_SERP_HEALTH_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-serp-health-latest.json} --manifest-path $${GENO_AU_P0B_GOOGLE_SERP_HEALTH_MANIFEST_PATH:-docs/runtime_preflight/au-p0b-google-serp-health-manifest-latest.json}

au-p0b-google-serp-fixture:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode google-serp-fixture --preflight-output-path $${GENO_AU_P0B_GOOGLE_SERP_FIXTURE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-serp-fixture-latest.json}

verify-au-p0b-google-serp-fixture:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_serp_comparison.py $${GENO_AU_P0B_GOOGLE_SERP_FIXTURE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-serp-fixture-latest.json} --require-comparison-ready --require-collector-health-ready

au-p0b-google-serp-fixture-manifest:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_preflight_manifest.py $${GENO_AU_P0B_GOOGLE_SERP_FIXTURE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-serp-fixture-latest.json} --manifest-path $${GENO_AU_P0B_GOOGLE_SERP_FIXTURE_MANIFEST_PATH:-docs/runtime_preflight/au-p0b-google-serp-fixture-manifest-latest.json}

au-p0b-google-serp-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_serp_status_report.py --output-path $${GENO_AU_P0B_GOOGLE_SERP_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-serp-status-latest.json}

verify-au-p0b-google-serp-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_serp_status_report.py $${GENO_AU_P0B_GOOGLE_SERP_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-serp-status-latest.json}

browser-fidelity-plan:
	@PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --plan-browser-fidelity-sampling

browser-fidelity-scheduler-plan:
	@PYTHONPATH=packages/geno_core:apps/api python3 scripts/run_browser_fidelity_scheduler.py

browser-fidelity-scheduler-run:
	@PYTHONPATH=packages/geno_core:apps/api python3 scripts/run_browser_fidelity_scheduler.py --execute

api-browser-fidelity-preflight:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode api --prompt-limit 1 --cities Sydney --sample-size 1 --include-browser-fidelity-playwright --require-ready-collectors --require-no-collection-failures

report-export-worker:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/report_export_worker/run_report_export_jobs.py

runtime-alert-notification-worker:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/notification_worker/run_runtime_alert_notifications.py --market-code $${GENO_RUNTIME_ALERT_MARKET_CODE:-AU}

runtime-alert-escalation-worker:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/notification_worker/run_runtime_alert_escalations.py --market-code $${GENO_RUNTIME_ALERT_MARKET_CODE:-AU}

notification-delivery-worker:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/notification_worker/run_notification_deliveries.py

worker-fixture:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode fixture

worker-fixture-persist:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode fixture --persist --persist-analysis

worker-google-fixture:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode google-fixture
