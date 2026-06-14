.PHONY: install-api-deps install-dev-deps lint-python compile-python web-typecheck quality test web-build docker-config docker-config-llm docker-config-scheduler docker-config-observability docker-config-db-smoke db-smoke runtime-e2e ci-local api-preflight verify-api-preflight preflight-manifest au-p0a-runbook verify-au-p0a-runbook verify-au-p0a-env-template au-p0a-env-bootstrap verify-au-p0a-env-bootstrap au-p0a-env verify-au-p0a-env au-p0a-environment-checklist verify-au-p0a-environment-checklist au-p0a-runbook-dry-run verify-au-p0a-runbook-execution au-p0a-readiness au-p0a-package verify-au-p0a-package au-p0a-status verify-au-p0a-status au-p0a-execution-checklist verify-au-p0a-execution-checklist au-p0a-credential-request verify-au-p0a-credential-request au-p0a-credential-fulfillment verify-au-p0a-credential-fulfillment au-p0a-real-batch-request verify-au-p0a-real-batch-request au-p0a-real-batch-fulfillment verify-au-p0a-real-batch-fulfillment au-launch-status verify-au-launch-status au-launch-remediation-plan verify-au-launch-remediation-plan au-handoff-dossier verify-au-handoff-dossier au-customer-handoff-readiness verify-au-customer-handoff-readiness au-next-work-item verify-au-next-work-item au-delivery-progress verify-au-delivery-progress au-external-dependency-handoff verify-au-external-dependency-handoff au-external-dependency-clearance verify-au-external-dependency-clearance au-broader-platform-registry verify-au-broader-platform-registry au-retest-scheduler-plan verify-au-retest-scheduler-plan au-retest-execution-status verify-au-retest-execution-status au-p0c-report-package verify-au-p0c-report-package au-p0b-google-runbook verify-au-p0b-google-runbook verify-au-p0b-google-env-template au-p0b-google-env-bootstrap verify-au-p0b-google-env-bootstrap au-p0b-google-runbook-dry-run verify-au-p0b-google-runbook-execution au-p0b-google-status verify-au-p0b-google-status au-p0b-google-package verify-au-p0b-google-package au-p0b-google-execution-checklist verify-au-p0b-google-execution-checklist au-p0b-google-environment-request verify-au-p0b-google-environment-request au-p0b-google-environment-fulfillment verify-au-p0b-google-environment-fulfillment au-p0b-google-manual-backfill-request verify-au-p0b-google-manual-backfill-request au-p0b-google-manual-backfill-fulfillment verify-au-p0b-google-manual-backfill-fulfillment au-p0b-google-phase-execution-request verify-au-p0b-google-phase-execution-request au-p0b-google-phase-execution-fulfillment verify-au-p0b-google-phase-execution-fulfillment au-p0b-google-manual-template verify-au-p0b-google-manual-backfill au-p0b-google-playwright-env verify-au-p0b-google-playwright-env au-p0b-google-playwright-smoke verify-au-p0b-google-playwright-smoke au-p0b-google-spike-health au-p0b-google-spike-health-manifest au-p0b-google-spike au-p0b-google-spike-manifest au-p0b-google-serp-health verify-au-p0b-google-serp-health au-p0b-google-serp-health-manifest au-p0b-google-serp-fixture verify-au-p0b-google-serp-fixture au-p0b-google-serp-fixture-manifest au-p0b-google-serp-status verify-au-p0b-google-serp-status browser-fidelity-plan browser-fidelity-scheduler-plan browser-fidelity-scheduler-run api-browser-fidelity-preflight report-export-worker runtime-alert-notification-worker runtime-alert-escalation-worker entity-alias-assignment-notification-worker notification-delivery-worker worker-fixture worker-fixture-persist worker-google-fixture

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

verify-au-p0a-env-template:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_env_template.py $${GENO_AU_P0A_ENV_TEMPLATE_PATH:-.env.au-p0a.example}

au-p0a-env-bootstrap:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/bootstrap_au_p0a_env_file.py --template-path $${GENO_AU_P0A_ENV_TEMPLATE_PATH:-.env.au-p0a.example} --env-file $${GENO_AU_P0A_ENV_FILE:-.env.au-p0a} --output-path $${GENO_AU_P0A_ENV_BOOTSTRAP_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-bootstrap-latest.json}

verify-au-p0a-env-bootstrap:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_env_file_bootstrap.py $${GENO_AU_P0A_ENV_BOOTSTRAP_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-bootstrap-latest.json}

au-p0a-env:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0a_env_report.py --runbook-path $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json} --env-file $${GENO_AU_P0A_ENV_FILE:-.env.au-p0a} --output-path $${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json}

verify-au-p0a-env:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_env_report.py $${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json}

au-p0a-environment-checklist:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0a_environment_checklist.py --runbook-path $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json} --environment-path $${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} --status-path $${GENO_AU_P0A_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-status-latest.json} --env-file $${GENO_AU_P0A_ENV_FILE:-.env.au-p0a} --output-path $${GENO_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-environment-checklist-latest.json}

verify-au-p0a-environment-checklist:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_environment_checklist.py $${GENO_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-environment-checklist-latest.json}

au-p0a-runbook-dry-run:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/run_au_p0a_runbook.py --runbook-path $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json} --env-file $${GENO_AU_P0A_ENV_FILE:-.env.au-p0a} --output-path $${GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-execution-latest.json}

verify-au-p0a-runbook-execution:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_runbook_execution.py $${GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-execution-latest.json}

au-p0a-readiness:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_readiness.py --phase $${GENO_AU_P0A_READINESS_PHASE:-preflight} --runbook-path $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json} --env-file $${GENO_AU_P0A_ENV_FILE:-.env.au-p0a} --output-path $${GENO_AU_P0A_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-readiness-latest.json}

au-p0a-package:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0a_evidence_package.py --runbook-path $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json} --environment-path $${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} --readiness-path $${GENO_AU_P0A_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-readiness-latest.json} --runbook-execution-path $${GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-execution-latest.json} --output-path $${GENO_AU_P0A_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-evidence-package-latest.json}

verify-au-p0a-package:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_evidence_package.py $${GENO_AU_P0A_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-evidence-package-latest.json}

au-p0a-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0a_status_report.py --runbook-path $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json} --environment-path $${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} --readiness-path $${GENO_AU_P0A_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-readiness-latest.json} --runbook-execution-path $${GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-execution-latest.json} --package-path $${GENO_AU_P0A_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-evidence-package-latest.json} --env-file $${GENO_AU_P0A_ENV_FILE:-.env.au-p0a} --output-path $${GENO_AU_P0A_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-status-latest.json}

verify-au-p0a-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_status_report.py $${GENO_AU_P0A_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-status-latest.json}

au-p0a-execution-checklist:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0a_execution_checklist.py --runbook-path $${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json} --environment-path $${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} --runbook-execution-path $${GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-execution-latest.json} --readiness-path $${GENO_AU_P0A_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-readiness-latest.json} --package-path $${GENO_AU_P0A_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-evidence-package-latest.json} --status-path $${GENO_AU_P0A_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-status-latest.json} --env-file $${GENO_AU_P0A_ENV_FILE:-.env.au-p0a} --output-path $${GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-execution-checklist-latest.json}

verify-au-p0a-execution-checklist:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_execution_checklist.py $${GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-execution-checklist-latest.json}

au-p0a-credential-request:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0a_credential_request_packet.py --p0a-execution-checklist-path $${GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-execution-checklist-latest.json} --output-path $${GENO_AU_P0A_CREDENTIAL_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-request-latest.json}

verify-au-p0a-credential-request:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_credential_request_packet.py $${GENO_AU_P0A_CREDENTIAL_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-request-latest.json}

au-p0a-credential-fulfillment:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0a_credential_fulfillment.py --credential-request-path $${GENO_AU_P0A_CREDENTIAL_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-request-latest.json} --env-report-path $${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} --output-path $${GENO_AU_P0A_CREDENTIAL_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-fulfillment-latest.json}

verify-au-p0a-credential-fulfillment:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_credential_fulfillment.py $${GENO_AU_P0A_CREDENTIAL_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-fulfillment-latest.json}

au-p0a-real-batch-request:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0a_real_batch_request_packet.py --p0a-execution-checklist-path $${GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-execution-checklist-latest.json} --output-path $${GENO_AU_P0A_REAL_BATCH_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-real-batch-request-latest.json}

verify-au-p0a-real-batch-request:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_real_batch_request_packet.py $${GENO_AU_P0A_REAL_BATCH_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-real-batch-request-latest.json}

au-p0a-real-batch-fulfillment:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0a_real_batch_fulfillment.py --real-batch-request-path $${GENO_AU_P0A_REAL_BATCH_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-real-batch-request-latest.json} --p0a-execution-checklist-path $${GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-execution-checklist-latest.json} --output-path $${GENO_AU_P0A_REAL_BATCH_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json}

verify-au-p0a-real-batch-fulfillment:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_real_batch_fulfillment.py $${GENO_AU_P0A_REAL_BATCH_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json}

au-launch-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_launch_status.py --p0a-status-path $${GENO_AU_P0A_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-status-latest.json} --p0b-google-status-path $${GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-status-latest.json} --p0b-google-package-path $${GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-evidence-package-latest.json} --p0b-google-runbook-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json} --p0b-google-execution-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-execution-latest.json} --p0c-report-package-path $${GENO_AU_P0C_REPORT_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0c-report-package-latest.json} --output-path $${GENO_AU_LAUNCH_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-launch-status-latest.json}

verify-au-launch-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_launch_status.py $${GENO_AU_LAUNCH_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-launch-status-latest.json}

au-launch-remediation-plan:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_launch_remediation_plan.py --launch-status-path $${GENO_AU_LAUNCH_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-launch-status-latest.json} --output-path $${GENO_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH:-docs/runtime_preflight/au-launch-remediation-plan-latest.json}

verify-au-launch-remediation-plan:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_launch_remediation_plan.py $${GENO_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH:-docs/runtime_preflight/au-launch-remediation-plan-latest.json}

au-handoff-dossier:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_handoff_dossier.py --launch-status-path $${GENO_AU_LAUNCH_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-launch-status-latest.json} --remediation-plan-path $${GENO_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH:-docs/runtime_preflight/au-launch-remediation-plan-latest.json} --p0a-environment-checklist-path $${GENO_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-environment-checklist-latest.json} --p0a-execution-checklist-path $${GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-execution-checklist-latest.json} --p0b-google-execution-checklist-path $${GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json} --output-path $${GENO_AU_HANDOFF_DOSSIER_OUTPUT_PATH:-docs/runtime_preflight/au-handoff-dossier-latest.json} --markdown-output-path $${GENO_AU_HANDOFF_DOSSIER_MARKDOWN_PATH:-docs/runtime_preflight/au-handoff-dossier-latest.md}

verify-au-handoff-dossier:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_handoff_dossier.py $${GENO_AU_HANDOFF_DOSSIER_OUTPUT_PATH:-docs/runtime_preflight/au-handoff-dossier-latest.json}

au-customer-handoff-readiness:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_customer_handoff_readiness.py --handoff-dossier-path $${GENO_AU_HANDOFF_DOSSIER_OUTPUT_PATH:-docs/runtime_preflight/au-handoff-dossier-latest.json} --output-path $${GENO_AU_CUSTOMER_HANDOFF_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-readiness-latest.json}

verify-au-customer-handoff-readiness:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_readiness.py $${GENO_AU_CUSTOMER_HANDOFF_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-readiness-latest.json}

au-next-work-item:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_next_work_item_packet.py --handoff-dossier-path $${GENO_AU_HANDOFF_DOSSIER_OUTPUT_PATH:-docs/runtime_preflight/au-handoff-dossier-latest.json} --external-dependency-handoff-path $${GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH:-docs/runtime_preflight/au-external-dependency-handoff-latest.json} --output-path $${GENO_AU_NEXT_WORK_ITEM_OUTPUT_PATH:-docs/runtime_preflight/au-next-work-item-latest.json}

verify-au-next-work-item:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_next_work_item_packet.py $${GENO_AU_NEXT_WORK_ITEM_OUTPUT_PATH:-docs/runtime_preflight/au-next-work-item-latest.json}

au-delivery-progress:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_delivery_progress.py --launch-status-path $${GENO_AU_LAUNCH_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-launch-status-latest.json} --handoff-dossier-path $${GENO_AU_HANDOFF_DOSSIER_OUTPUT_PATH:-docs/runtime_preflight/au-handoff-dossier-latest.json} --customer-handoff-readiness-path $${GENO_AU_CUSTOMER_HANDOFF_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-readiness-latest.json} --next-work-item-path $${GENO_AU_NEXT_WORK_ITEM_OUTPUT_PATH:-docs/runtime_preflight/au-next-work-item-latest.json} --external-dependency-handoff-path $${GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH:-docs/runtime_preflight/au-external-dependency-handoff-latest.json} --external-dependency-clearance-path $${GENO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-external-dependency-clearance-latest.json} --output-path $${GENO_AU_DELIVERY_PROGRESS_OUTPUT_PATH:-docs/runtime_preflight/au-delivery-progress-latest.json}

verify-au-delivery-progress:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_delivery_progress.py $${GENO_AU_DELIVERY_PROGRESS_OUTPUT_PATH:-docs/runtime_preflight/au-delivery-progress-latest.json}

au-external-dependency-handoff:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_external_dependency_handoff.py --launch-status-path $${GENO_AU_LAUNCH_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-launch-status-latest.json} --remediation-plan-path $${GENO_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH:-docs/runtime_preflight/au-launch-remediation-plan-latest.json} --p0a-environment-checklist-path $${GENO_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-environment-checklist-latest.json} --p0a-execution-checklist-path $${GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-execution-checklist-latest.json} --p0b-google-execution-checklist-path $${GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json} --output-path $${GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH:-docs/runtime_preflight/au-external-dependency-handoff-latest.json}

verify-au-external-dependency-handoff:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_external_dependency_handoff.py $${GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH:-docs/runtime_preflight/au-external-dependency-handoff-latest.json}

au-external-dependency-clearance:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/run_au_external_dependency_clearance.py --handoff-path $${GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH:-docs/runtime_preflight/au-external-dependency-handoff-latest.json} --output-path $${GENO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-external-dependency-clearance-latest.json}

verify-au-external-dependency-clearance:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_external_dependency_clearance.py $${GENO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-external-dependency-clearance-latest.json}

au-broader-platform-registry:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_broader_platform_registry.py --output-path $${GENO_AU_BROADER_PLATFORM_REGISTRY_OUTPUT_PATH:-docs/runtime_preflight/au-broader-platform-registry-latest.json}

verify-au-broader-platform-registry:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_broader_platform_registry.py $${GENO_AU_BROADER_PLATFORM_REGISTRY_OUTPUT_PATH:-docs/runtime_preflight/au-broader-platform-registry-latest.json}

au-retest-scheduler-plan:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_retest_scheduler_plan.py --output-path $${GENO_AU_RETEST_SCHEDULER_PLAN_OUTPUT_PATH:-docs/runtime_preflight/au-retest-scheduler-plan-latest.json}

verify-au-retest-scheduler-plan:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_retest_scheduler_plan.py $${GENO_AU_RETEST_SCHEDULER_PLAN_OUTPUT_PATH:-docs/runtime_preflight/au-retest-scheduler-plan-latest.json}

au-retest-execution-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_retest_execution_status.py --plan-path $${GENO_AU_RETEST_SCHEDULER_PLAN_OUTPUT_PATH:-docs/runtime_preflight/au-retest-scheduler-plan-latest.json} --output-path $${GENO_AU_RETEST_EXECUTION_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-retest-execution-status-latest.json}

verify-au-retest-execution-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_retest_execution_status.py $${GENO_AU_RETEST_EXECUTION_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-retest-execution-status-latest.json}

au-p0c-report-package:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0c_report_package.py --output-path $${GENO_AU_P0C_REPORT_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0c-report-package-latest.json}

verify-au-p0c-report-package:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0c_report_package.py $${GENO_AU_P0C_REPORT_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0c-report-package-latest.json}

au-p0b-google-runbook:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_spike_runbook.py --output-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json}

verify-au-p0b-google-runbook:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_spike_runbook.py $${GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json}

verify-au-p0b-google-env-template:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_env_template.py $${GENO_AU_P0B_GOOGLE_ENV_TEMPLATE_PATH:-.env.au-p0b-google.example}

au-p0b-google-env-bootstrap:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/bootstrap_au_p0b_google_env_file.py --template-path $${GENO_AU_P0B_GOOGLE_ENV_TEMPLATE_PATH:-.env.au-p0b-google.example} --env-file $${GENO_AU_P0B_GOOGLE_ENV_FILE:-.env.au-p0b-google} --output-path $${GENO_AU_P0B_GOOGLE_ENV_BOOTSTRAP_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-env-bootstrap-latest.json}

verify-au-p0b-google-env-bootstrap:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_env_file_bootstrap.py $${GENO_AU_P0B_GOOGLE_ENV_BOOTSTRAP_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-env-bootstrap-latest.json}

au-p0b-google-runbook-dry-run:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/run_au_p0b_google_spike_runbook.py --runbook-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json} --output-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-execution-latest.json}

verify-au-p0b-google-runbook-execution:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_spike_runbook_execution.py $${GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-execution-latest.json}

au-p0b-google-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_spike_status_report.py --runbook-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json} --execution-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-execution-latest.json} --output-path $${GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-status-latest.json}

verify-au-p0b-google-status:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_spike_status_report.py $${GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-status-latest.json}

au-p0b-google-package:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_evidence_package.py --runbook-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json} --execution-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-execution-latest.json} --status-report-path $${GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-status-latest.json} --output-path $${GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-evidence-package-latest.json}

verify-au-p0b-google-package:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_evidence_package.py $${GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-evidence-package-latest.json}

au-p0b-google-execution-checklist:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_execution_checklist.py --runbook-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json} --execution-path $${GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-runbook-execution-latest.json} --playwright-env-path $${GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-env-latest.json} --status-report-path $${GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-status-latest.json} --package-path $${GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-evidence-package-latest.json} --env-file $${GENO_AU_P0B_GOOGLE_ENV_FILE:-.env.au-p0b-google} --output-path $${GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json}

verify-au-p0b-google-execution-checklist:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_execution_checklist.py $${GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json}

au-p0b-google-environment-request:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_environment_request_packet.py --p0b-google-execution-checklist-path $${GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json} --p0a-env-report-path $${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} --output-path $${GENO_AU_P0B_GOOGLE_ENVIRONMENT_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-environment-request-latest.json}

verify-au-p0b-google-environment-request:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_environment_request_packet.py $${GENO_AU_P0B_GOOGLE_ENVIRONMENT_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-environment-request-latest.json}

au-p0b-google-environment-fulfillment:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_environment_fulfillment.py --environment-request-path $${GENO_AU_P0B_GOOGLE_ENVIRONMENT_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-environment-request-latest.json} --playwright-env-report-path $${GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-env-latest.json} --env-file $${GENO_AU_P0B_GOOGLE_ENV_FILE:-.env.au-p0b-google} --output-path $${GENO_AU_P0B_GOOGLE_ENVIRONMENT_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-environment-fulfillment-latest.json}

verify-au-p0b-google-environment-fulfillment:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_environment_fulfillment.py $${GENO_AU_P0B_GOOGLE_ENVIRONMENT_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-environment-fulfillment-latest.json}

au-p0b-google-manual-backfill-request:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_manual_backfill_request_packet.py --p0b-google-execution-checklist-path $${GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json} --output-path $${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-request-latest.json}

verify-au-p0b-google-manual-backfill-request:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_manual_backfill_request_packet.py $${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-request-latest.json}

au-p0b-google-manual-backfill-fulfillment:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_manual_backfill_fulfillment.py --manual-backfill-request-path $${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-request-latest.json} --manual-backfill-verification-path $${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_VERIFICATION_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json} --manual-jsonl-path $${MANUAL_BACKFILL_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-template.jsonl} --output-path $${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-fulfillment-latest.json}

verify-au-p0b-google-manual-backfill-fulfillment:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_manual_backfill_fulfillment.py $${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-fulfillment-latest.json}

au-p0b-google-phase-execution-request:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_phase_execution_request_packet.py --p0b-google-execution-checklist-path $${GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json} --output-path $${GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-phase-execution-request-latest.json}

verify-au-p0b-google-phase-execution-request:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_phase_execution_request_packet.py $${GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-phase-execution-request-latest.json}

au-p0b-google-phase-execution-fulfillment:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_au_p0b_google_phase_execution_fulfillment.py --phase-execution-request-path $${GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-phase-execution-request-latest.json} --p0b-google-execution-checklist-path $${GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json} --output-path $${GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json}

verify-au-p0b-google-phase-execution-fulfillment:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_phase_execution_fulfillment.py $${GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json}

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

au-p0b-google-spike-health:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode google-spike --require-ready-collectors --health-check-only --preflight-output-path $${GENO_AU_P0B_GOOGLE_SPIKE_HEALTH_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-health-latest.json}

au-p0b-google-spike-health-manifest:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_preflight_manifest.py $${GENO_AU_P0B_GOOGLE_SPIKE_HEALTH_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-health-latest.json} --manifest-path $${GENO_AU_P0B_GOOGLE_SPIKE_HEALTH_MANIFEST_PATH:-docs/runtime_preflight/au-p0b-google-spike-health-manifest-latest.json}

au-p0b-google-spike:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode google-spike --require-ready-collectors --require-no-collection-failures --require-google-spike-gates $${GENO_AU_P0B_GOOGLE_SPIKE_PERSIST_ARGS---persist} --preflight-output-path $${GENO_AU_P0B_GOOGLE_SPIKE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-latest.json}

au-p0b-google-spike-manifest:
	PYTHONPATH=packages/geno_core:apps/api python3 scripts/build_preflight_manifest.py $${GENO_AU_P0B_GOOGLE_SPIKE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-latest.json} --manifest-path $${GENO_AU_P0B_GOOGLE_SPIKE_MANIFEST_PATH:-docs/runtime_preflight/au-p0b-google-spike-manifest-latest.json}

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

entity-alias-assignment-notification-worker:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/notification_worker/run_entity_alias_assignment_notifications.py --market-code $${GENO_ENTITY_ALIAS_ASSIGNMENT_MARKET_CODE:-AU}

notification-delivery-worker:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/notification_worker/run_notification_deliveries.py

worker-fixture:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode fixture

worker-fixture-persist:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode fixture --persist --persist-analysis

worker-google-fixture:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode google-fixture
