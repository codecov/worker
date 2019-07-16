-include .envrc

GCLOUD_SERVICE_KEY := $(shell cat ~/.gcloud/codecov-enterprise-sandbox-03eb0a0ecaf2.json | base64 --wrap=0)

circleci-local:
	circleci local execute -c .circleci/local.yml --job build --env GH_ACCESS_TOKEN=${GH_ACCESS_TOKEN} --env GCLOUD_SERVICE_KEY="${GCLOUD_SERVICE_KEY}" --env GOOGLE_COMPUTE_ZONE=us-east4 --env GOOGLE_PROJECT_ID=codecov-enterprise-sandbox

build:
	docker build -f Dockerfile . -t codecov/worker:latest --build-arg GH_ACCESS_TOKEN=${GH_ACCESS_TOKEN}
	docker tag codecov/worker gcr.io/codecov-enterprise-sandbox/codecov-worker:latest

push:
	docker push us.gcr.io/codecov-enterprise-sandbox/codecov-worker:latest

tag:
	get checkout master
	git pull
	docker push gcr.io/codecov-enterprise-sandbox/codecov-worker:${VERSION}
	git tag ${VERSION}
	git push --tags
