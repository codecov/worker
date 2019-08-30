-include .envrc

#GCLOUD_SERVICE_KEY := $(shell cat ~/.gcloud/codecov-enterprise-sandbox-03eb0a0ecaf2.json | base64 --wrap=0)
GCR_REPO := gcr.io/codecov-enterprise-sandbox/codecov-worker
REQUIREMENTS_TAG := requirements-$(shell sha1sum requirements.txt | cut -d ' ' -f 1)

# CIRCLECI
# job: build
# builds an intermediate image with dependencies if there were changes to
# requirements.txt
build-requirements:
	# if docker pull succeeds, we have already build this version of
	# requirements.txt.  Otherwise, build and push a version tagged
	# with the hash of this requirements.txt
	docker pull ${GCR_REPO}:${REQUIREMENTS_TAG} || docker build \
		-f Dockerfile.requirements . \
		-t ${GCR_REPO}:${REQUIREMENTS_TAG} \
		--build-arg GH_ACCESS_TOKEN=${GH_ACCESS_TOKEN} \
	&& docker push ${GCR_REPO}:${REQUIREMENTS_TAG}

# CIRCLECI
# job: build
# pulls intermediate dependencies image and adds app code
build:
	docker pull ${GCR_REPO}:${REQUIREMENTS_TAG}
	docker build \
		-f Dockerfile . \
		-t ${GCR_REPO}:latest \
		--build-arg REQUIREMENTS_IMAGE=${GCR_REPO}:${REQUIREMENTS_TAG}

# CIRCLECI
# job: test
# used to push latest image tag after a successful test
push:
	docker push ${GCR_REPO}:latest

# CIRCLECI
# job: deploy
# tags latest image with git tag
tag:
	docker pull ${GCR_REPO}:latest
	docker tag ${GCR_REPO}:latest ${GCR_REPO}:${VERSION}
	docker push ${GCR_REPO}:${VERSION}

# CIRCLECI
# job: deploy
# deploys tagged version to production k8s
deploy:
	kubectl set image deployment/worker workers=${GCR_REPO}:${VERSION}
	kubectl rollout status deployments worker

# LOCAL
# used to test circleci jobs
# example$ make circleci-local JOB=build
circleci-local:
	circleci local execute \
		-c .circleci/local.yml \
		--job ${JOB} \
		--env GH_ACCESS_TOKEN=${GH_ACCESS_TOKEN} \
		--env GCLOUD_SERVICE_KEY=${GCLOUD_SERVICE_KEY} \
		--env GOOGLE_COMPUTE_ZONE=us-east4 \
		--env GOOGLE_PROJECT_ID=codecov-enterprise-sandbox \
		--env VERSION=${VERSION}

# LOCAL
# use locally to tag a new release version.  
# this will trigger a build/test/deployment on circle ci
release:
	git tag ${VERSION}
	git push --tags
