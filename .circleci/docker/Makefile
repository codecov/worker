GCR_REPO := gcr.io/test6u3411ty6xqh462sri/codecov-deploy

build:
	docker build \
		-f Dockerfile.deploy \
		-t ${GCR_REPO}:latest .

push:
	docker push ${GCR_REPO}:latest
