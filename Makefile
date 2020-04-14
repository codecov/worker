sha := $(shell git rev-parse --short=7 HEAD)
version := 4.5.0
_gcr := gcr.io/test6u3411ty6xqh462sri/codecov
ssh_private_key = `cat ~/.ssh/codecov-io_rsa`

build:
	docker build -f dockerscripts/Dockerfile . -t codecov/worker:latest

build.base:
	docker build -f dockerscripts/Dockerfile.base . -t codecov/baseworker:latest --build-arg SSH_PRIVATE_KEY="${ssh_private_key}"

build.enterprise:
	docker build -f dockerscripts/Dockerfile.enterprise . -t codecov/enterprise:v${version}

test:
	python -m pytest --cov=./

test.unit:
	python -m pytest --cov=./ -m "not integration" --cov-report=xml:unit.coverage.xml

test.integration:
	python -m pytest --cov=./ -m "integration" --cov-report=xml:integration.coverage.xml

push.worker-new:
	docker tag codecov/worker ${_gcr}-worker:${version}-${sha}
	docker push ${_gcr}-worker:${version}-${sha}

worker-new.deploy:
	kubectl set image deployment/worker-new-standard worker-new-standard=${_gcr}-worker:${version}-${sha}
	kubectl rollout status deployments worker-new-standard
