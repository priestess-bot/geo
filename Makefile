.PHONY: install-api-deps test docker-config docker-config-llm runtime-e2e api-preflight browser-fidelity-plan api-browser-fidelity-preflight worker-fixture worker-fixture-persist worker-google-fixture

install-api-deps:
	python3 -m pip install -r apps/api/requirements.txt

test:
	PYTHONPATH=packages/geno_core:apps/api python3 -m unittest discover -s tests

docker-config:
	docker compose -f infra/docker-compose.yml config

docker-config-llm:
	docker compose -f infra/docker-compose.yml --profile llm-gateway config

runtime-e2e:
	set -e; \
	trap 'docker compose -p geno-runtime-e2e -f infra/docker-compose.yml --profile e2e down -v' EXIT; \
	docker compose -p geno-runtime-e2e -f infra/docker-compose.yml --profile e2e build runtime-e2e; \
	docker compose -p geno-runtime-e2e -f infra/docker-compose.yml --profile e2e run --rm runtime-e2e

api-preflight:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode api --prompt-limit 1 --cities Sydney --sample-size 3 --require-ready-collectors --require-p0a-readiness

browser-fidelity-plan:
	@PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --plan-browser-fidelity-sampling

api-browser-fidelity-preflight:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode api --prompt-limit 1 --cities Sydney --sample-size 1 --include-browser-fidelity-playwright --require-ready-collectors --require-no-collection-failures

worker-fixture:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode fixture

worker-fixture-persist:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode fixture --persist --persist-analysis

worker-google-fixture:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode google-fixture
