sha := $(shell git rev-parse --short=7 HEAD)
version := 4.4.9
_gcr := gcr.io/test6u3411ty6xqh462sri/codecov
ssh_private_key = `cat ~/.ssh/codecov-io_rsa`

build:
	docker build -f Dockerfile . -t codecov/worker:latest --build-arg SSH_PRIVATE_KEY="${ssh_private_key}"

test:
	python -m pytest --cov=./

push.worker-new:
	docker tag codecov/worker ${_gcr}-worker:${version}-${sha}
	docker push ${_gcr}-worker:${version}-${sha}

worker-new.deploy:
	kubectl set image deployment/worker-new-standard worker-new-standard=${_gcr}-worker:${version}-${sha}
	kubectl rollout status deployments worker-new-standard

show_vars:
	echo ${sha}
	echo ${version}
	echo ${_gcr}
