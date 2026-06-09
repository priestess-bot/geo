.PHONY: install-api-deps test docker-config worker-fixture worker-fixture-persist worker-google-fixture

install-api-deps:
	python3 -m pip install -r apps/api/requirements.txt

test:
	PYTHONPATH=packages/geno_core:apps/api python3 -m unittest discover -s tests

docker-config:
	docker compose -f infra/docker-compose.yml config

worker-fixture:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode fixture

worker-fixture-persist:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode fixture --persist --persist-analysis

worker-google-fixture:
	PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode google-fixture
