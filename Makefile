.PHONY: install-api-deps test docker-config

install-api-deps:
	python3 -m pip install -r apps/api/requirements.txt

test:
	PYTHONPATH=packages/geno_core:apps/api python3 -m unittest discover -s tests

docker-config:
	docker compose -f infra/docker-compose.yml config
