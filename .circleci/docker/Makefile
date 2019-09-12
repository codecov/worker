GCR_REPO := gcr.io/codecov-enterprise-sandbox/codecov-deploy

build:
	docker build \
		-f Dockerfile.deploy \
		-t ${GCR_REPO}:latest .

push:
	docker push ${GCR_REPO}:latest
