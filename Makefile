-include .envrc

#GCLOUD_SERVICE_KEY := $(shell cat ~/.gcloud/codecov-enterprise-sandbox-03eb0a0ecaf2.json | base64 --wrap=0)
GCR_REPO := gcr.io/codecov-enterprise-sandbox/codecov-worker
#REQUIREMENTS_HASH := 
REQUIREMENTS_TAG := requirements-$(shell sha1sum requirements.txt | cut -d ' ' -f 1)

circleci-local:
	circleci local execute \
		-c .circleci/local.yml \
		--job ${JOB} \
		--env GH_ACCESS_TOKEN=${GH_ACCESS_TOKEN} \
		--env GCLOUD_SERVICE_KEY=${GCLOUD_SERVICE_KEY} \
		--env GOOGLE_COMPUTE_ZONE=us-east4 \
		--env GOOGLE_PROJECT_ID=codecov-enterprise-sandbox \
		--env VERSION=${VERSION}

build-requirements:
	# if docker pull succeeds, we have already build this version of
	# requirements.txt.  Otherwise, build and push a version tagged
	# with the hash of this requirements.txt
	docker pull ${GCR_REPO}:${REQUIREMENTS_TAG} || docker build \
		-f Dockerfile.requirements . \
		-t codecov/worker:${REQUIREMENTS_TAG} \
		--build-arg GH_ACCESS_TOKEN=${GH_ACCESS_TOKEN} \
	&& docker tag codecov/worker ${GCR_REPO}:${REQUIREMENTS_TAG}

push-requirements:
	docker push ${GCR_REPO}:${REQUIREMENTS_TAG}

build:
	docker pull ${GCR_REPO}:${REQUIREMENTS_TAG}
	docker build \
		-f Dockerfile . \
		-t codecov/worker:latest \
		--build-arg REQUIREMENTS_IMAGE=${GCR_REPO}:${REQUIREMENTS_TAG}

push:
	docker tag codecov/worker ${GCR_REPO}:latest
	docker push ${GCR_REPO}:latest

tag:
	docker pull ${GCR_REPO}:latest
	docker tag ${GCR_REPO}:latest ${GCR_REPO}:${VERSION}
	docker push ${GCR_REPO}:${VERSION}

release:
	git tag ${VERSION}
	git push --tags

deploy:
	kubectl set image deployment/worker workers=${GCR_REPO}:${VERSION}
	kubectl rollout status deployments worker
