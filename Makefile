.PHONY: test docker-config

test:
	PYTHONPATH=packages/geno_core python3 -m unittest discover -s tests

docker-config:
	docker compose -f infra/docker-compose.yml config
