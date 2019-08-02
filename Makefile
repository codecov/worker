-include .envrc

GCLOUD_SERVICE_KEY := $(shell cat ~/.gcloud/codecov-enterprise-sandbox-03eb0a0ecaf2.json | base64 --wrap=0)
GCR_REPO := gcr.io/codecov-enterprise-sandbox/codecov-worker

circleci-local:
	circleci local execute \
		-c .circleci/local.yml \
		--job build \
		--env GH_ACCESS_TOKEN=${GH_ACCESS_TOKEN} \
		--env GCLOUD_SERVICE_KEY="${GCLOUD_SERVICE_KEY}" \
		--env GOOGLE_COMPUTE_ZONE=us-east4 \
		--env GOOGLE_PROJECT_ID=codecov-enterprise-sandbox \
		--env VERSION=${VERSION}

build:
	docker build \
		-f Dockerfile . \
		-t codecov/worker:latest \
		--build-arg GH_ACCESS_TOKEN=${GH_ACCESS_TOKEN}
	docker tag codecov/worker ${GCR_REPO}:latest
	docker tag codecov/worker ${GCR_REPO}:${VERSION}

push:
	docker push ${GCR_REPO}:latest
	docker push ${GCR_REPO}:${VERSION}

tag:
	docker tag codecov/worker ${GCR_REPO}:${VERSION}
	docker push ${GCR_REPO}:${VERSION}
	git tag ${VERSION}
	git push --tags

deploy:
	kubectl set image deployment/worker workers=${GCR_REPO}:${VERSION}
	kubectl rollout status deployments worker
