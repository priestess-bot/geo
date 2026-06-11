.PHONY: install-api-deps test web-build docker-config docker-config-llm docker-config-scheduler docker-config-observability runtime-e2e ci-local api-preflight browser-fidelity-plan browser-fidelity-scheduler-plan browser-fidelity-scheduler-run api-browser-fidelity-preflight worker-fixture worker-fixture-persist worker-google-fixture

install-api-deps:
	python3 -m pip install -r apps/api/requirements.txt

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

runtime-e2e:
	set -e; \
	trap 'docker compose -p geno-runtime-e2e -f infra/docker-compose.yml --profile e2e down -v' EXIT; \
	docker compose -p geno-runtime-e2e -f infra/docker-compose.yml --profile e2e build runtime-e2e; \
	docker compose -p geno-runtime-e2e -f infra/docker-compose.yml --profile e2e run --rm runtime-e2e

ci-local: test web-build docker-config docker-config-llm docker-config-scheduler docker-config-observability runtime-e2e

api-preflight:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode api --prompt-limit 1 --cities Sydney --sample-size 3 --require-ready-collectors --require-p0a-readiness --preflight-output-path $${GENO_API_PREFLIGHT_OUTPUT_PATH:-docs/runtime_preflight/api-preflight-latest.json}

browser-fidelity-plan:
	@PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --plan-browser-fidelity-sampling

browser-fidelity-scheduler-plan:
	@PYTHONPATH=packages/geno_core:apps/api python3 scripts/run_browser_fidelity_scheduler.py

browser-fidelity-scheduler-run:
	@PYTHONPATH=packages/geno_core:apps/api python3 scripts/run_browser_fidelity_scheduler.py --execute

api-browser-fidelity-preflight:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode api --prompt-limit 1 --cities Sydney --sample-size 1 --include-browser-fidelity-playwright --require-ready-collectors --require-no-collection-failures

worker-fixture:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode fixture

worker-fixture-persist:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode fixture --persist --persist-analysis

worker-google-fixture:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode google-fixture
