sha := $(shell git rev-parse --short=7 HEAD)
release_version = `cat VERSION`
_gcr := gcr.io/test6u3411ty6xqh462sri/codecov
ssh_private_key = `cat ~/.ssh/codecov-io_rsa`

build:
	docker build -f dockerscripts/Dockerfile . -t codecov/worker:latest --build-arg RELEASE_VERSION="${release_version}"

build.base:
	docker build -f dockerscripts/Dockerfile.base . -t codecov/baseworker:latest --build-arg SSH_PRIVATE_KEY="${ssh_private_key}"

build.enterprise:
	docker build -f dockerscripts/Dockerfile.enterprise . -t codecov/enterprise-worker:${release_version}

# for building and pushing private images to dockerhub. This is useful if you 
# need to push a test image for enterprise to test in sandbox deployments.
build.enterprise-private: 
	docker build -f dockerscripts/Dockerfile.enterprise . -t codecov/worker-private:${release_version}-${sha}

test:
	python -m pytest --cov=./

test.unit:
	python -m pytest --cov=./ -m "not integration" --cov-report=xml:unit.coverage.xml

test.integration:
	python -m pytest --cov=./ -m "integration" --cov-report=xml:integration.coverage.xml

push.worker-new:
	docker tag codecov/worker ${_gcr}-worker:${release_version}-${sha}
	docker push ${_gcr}-worker:${release_version}-${sha}

push.enterprise-private:
	docker push codecov/worker-private:${release_version}-${sha}

push.enterprise:
	docker push codecov/enterprise-worker:${release_version}

worker-new.deploy:
	kubectl set image deployment/worker-new-standard worker-new-standard=${_gcr}-worker:${release_version}-${sha}
	kubectl rollout status deployments worker-new-standard
