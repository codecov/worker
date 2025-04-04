sha ?= $(shell git rev-parse --short=7 HEAD)
full_sha ?= $(shell git rev-parse HEAD)
release_version = `cat VERSION`
_gcr := ${CODECOV_WORKER_GCR_REPO_BASE}
merge_sha ?= $(shell git merge-base HEAD^ origin/main)
build_date ?= $(shell git show -s --date=iso8601-strict --pretty=format:%cd $$sha)
name ?= worker
branch ?= $(shell git branch | grep \* | cut -f2 -d' ')
gh_access_token := $(shell echo ${GH_ACCESS_TOKEN})
epoch ?= $(shell date +"%s")

AR_REPO ?= codecov/worker
DOCKERHUB_REPO ?= codecov/self-hosted-worker
VERSION ?= release-${sha}
CODECOV_UPLOAD_TOKEN ?= "notset"
CODECOV_STATIC_TOKEN ?= "notset"
CODECOV_URL ?= "https://api.codecov.io"

DEFAULT_REQS_TAG := requirements-v1-$(shell sha1sum uv.lock | cut -d ' ' -f 1)-$(shell sha1sum docker/Dockerfile.requirements | cut -d ' ' -f 1)
REQUIREMENTS_TAG ?= ${DEFAULT_REQS_TAG}

# We allow this to be overridden so that we can run `pytest` from this directory
# but have the junit file use paths relative to a parent directory. This will
# help us move to a monorepo.
PYTEST_ROOTDIR ?= "."

export DOCKER_BUILDKIT=1
export WORKER_DOCKER_REPO=${AR_REPO}
export WORKER_DOCKER_VERSION=${VERSION}
export CODECOV_TOKEN=${CODECOV_UPLOAD_TOKEN}

# Codecov CLI version to use
CODECOV_CLI_VERSION := 0.5.1

build:
	$(MAKE) build.requirements
	$(MAKE) build.local


# for portable builds to dockerhub, for use with local development and
# acceptance testing.
build.portable:
	docker build -f dockerscripts/Dockerfile . -t codecov/$(name)-portable \
		--label "org.label-schema.build-date"="$(build_date)" \
		--label "org.label-schema.name"="$(name)" \
		--label "org.label-schema.vcs-ref"="$(sha)" \
		--label "org.label-schema.vendor"="Codecov" \
		--label "org.label-schema.version"="${release_version}-${sha}" \
		--label "org.vcs-branch"="$(branch)" \
		--build-arg GH_ACCESS_TOKEN=${gh_access_token} \
		--build-arg COMMIT_SHA="${sha}" \
		--build-arg RELEASE_VERSION="${release_version}"

test:
	COVERAGE_CORE=sysmon pytest --cov=./ --junitxml=junit.xml -o junit_family=legacy -c pytest.ini --rootdir=${PYTEST_ROOTDIR}

test.unit:
	COVERAGE_CORE=sysmon pytest --cov=./ -m "not integration" --cov-report=xml:unit.coverage.xml --junitxml=unit.junit.xml -o junit_family=legacy -c pytest.ini --rootdir=${PYTEST_ROOTDIR}

test.integration:
	COVERAGE_CORE=sysmon pytest --cov=./ -m "integration" --cov-report=xml:integration.coverage.xml --junitxml=integration.junit.xml -o junit_family=legacy -c pytest.ini --rootdir=${PYTEST_ROOTDIR}

lint:
	make lint.install
	make lint.run

# used for CI
lint.install:
	echo "Installing..."
	pip install -Iv ruff

lint.local:
	make lint.install.local
	make lint.run

lint.install.local:
	echo "Installing..."
	uv add --dev ruff

# The preferred method (for now) w.r.t. fixable rules is to manually update the makefile
# with --fix and re-run 'make lint.' Since ruff is constantly adding rules this is a slight
# amount of "needed" friction imo.
lint.run:
	ruff check
	ruff format

lint.check:
	echo "Linting..."
	ruff check
	echo "Formatting..."
	ruff format --check

build.requirements:
	# If make was given a different requirements tag, we assume a suitable image
	# was already built (e.g. by umbrella) and don't want to build this one.
	ifneq (${REQUIREMENTS_TAG},${DEFAULT_REQS_TAG})
	echo "Error: building worker reqs image despite another being provided"
	exit 1
	endif
	# if docker pull succeeds, we have already build this version of
	# requirements.txt.  Otherwise, build and push a version tagged
	# with the hash of this requirements.txt
	docker pull ${AR_REPO}:${REQUIREMENTS_TAG} || docker build \
		-f docker/Dockerfile.requirements . \
		-t ${AR_REPO}:${REQUIREMENTS_TAG} \
		-t codecov/worker-ci-requirements:${REQUIREMENTS_TAG}

build.local:
	docker build -f docker/Dockerfile . \
		-t ${AR_REPO}:latest \
		-t ${AR_REPO}:${VERSION} \
		--build-arg REQUIREMENTS_IMAGE=${AR_REPO}:${REQUIREMENTS_TAG} \
		--build-arg BUILD_ENV=local

build.app:
	docker build -f docker/Dockerfile . \
		-t ${AR_REPO}:latest \
		-t ${AR_REPO}:${VERSION} \
		--label "org.label-schema.vendor"="Codecov" \
		--label "org.label-schema.version"="${release_version}-${sha}" \
		--label "org.opencontainers.image.revision"="$(full_sha)" \
		--label "org.opencontainers.image.source"="github.com/codecov/worker" \
		--build-arg REQUIREMENTS_IMAGE=${AR_REPO}:${REQUIREMENTS_TAG} \
		--build-arg RELEASE_VERSION=${VERSION} \
		--build-arg BUILD_ENV=cloud

build.self-hosted:
	make build.self-hosted-base
	make build.self-hosted-runtime

build.self-hosted-base:
	docker build -f docker/Dockerfile . \
		-t ${DOCKERHUB_REPO}:latest-no-dependencies \
		-t ${DOCKERHUB_REPO}:${VERSION}-no-dependencies \
		--build-arg REQUIREMENTS_IMAGE=${AR_REPO}:${REQUIREMENTS_TAG} \
		--build-arg RELEASE_VERSION=${VERSION} \
		--build-arg BUILD_ENV=self-hosted

build.self-hosted-runtime:
	docker build -f docker/Dockerfile . \
		-t ${DOCKERHUB_REPO}:latest \
		-t ${DOCKERHUB_REPO}:${VERSION} \
		--label "org.label-schema.vendor"="Codecov" \
		--label "org.label-schema.version"="${release_version}-${sha}" \
		--build-arg REQUIREMENTS_IMAGE=${AR_REPO}:${REQUIREMENTS_TAG} \
        --build-arg RELEASE_VERSION=${VERSION} \
        --build-arg BUILD_ENV=self-hosted-runtime

tag.latest:
	docker tag ${AR_REPO}:${VERSION} ${AR_REPO}:latest

tag.staging:
	docker tag ${AR_REPO}:${VERSION} ${AR_REPO}:staging-${VERSION}

tag.production:
	docker tag ${AR_REPO}:${VERSION} ${AR_REPO}:production-${VERSION}

tag.self-hosted-rolling:
	docker tag ${DOCKERHUB_REPO}:${VERSION}-no-dependencies ${DOCKERHUB_REPO}:rolling_no_dependencies
	docker tag ${DOCKERHUB_REPO}:${VERSION} ${DOCKERHUB_REPO}:rolling

tag.self-hosted-release:
	docker tag ${DOCKERHUB_REPO}:${VERSION}-no-dependencies ${DOCKERHUB_REPO}:${release_version}_no_dependencies
	docker tag ${DOCKERHUB_REPO}:${VERSION}-no-dependencies ${DOCKERHUB_REPO}:latest_calver_no_dependencies
	docker tag ${DOCKERHUB_REPO}:${VERSION}-no-dependencies ${DOCKERHUB_REPO}:latest_stable_no_dependencies
	docker tag ${DOCKERHUB_REPO}:${VERSION} ${DOCKERHUB_REPO}:${release_version}
	docker tag ${DOCKERHUB_REPO}:${VERSION} ${DOCKERHUB_REPO}:latest-stable
	docker tag ${DOCKERHUB_REPO}:${VERSION} ${DOCKERHUB_REPO}:latest-calver

load.requirements:
	docker load --input requirements.tar
	docker tag codecov/worker-ci-requirements:${REQUIREMENTS_TAG} ${AR_REPO}:${REQUIREMENTS_TAG}

load.self-hosted:
	docker load --input self-hosted-runtime.tar
	docker load --input self-hosted.tar

save.app:
	docker save -o app.tar ${AR_REPO}:${VERSION}

save.requirements:
	docker tag ${AR_REPO}:${REQUIREMENTS_TAG} codecov/worker-ci-requirements:${REQUIREMENTS_TAG}
	docker save -o requirements.tar codecov/worker-ci-requirements:${REQUIREMENTS_TAG}

save.self-hosted:
	make save.self-hosted-base
	make save.self-hosted-runtime

save.self-hosted-base:
	docker save -o self-hosted.tar ${DOCKERHUB_REPO}:${VERSION}-no-dependencies

save.self-hosted-runtime:
	docker save -o self-hosted-runtime.tar ${DOCKERHUB_REPO}:${VERSION}

push.latest:
	docker push ${AR_REPO}:latest

push.staging:
	docker push ${AR_REPO}:staging-${VERSION}

push.production:
	docker push ${AR_REPO}:production-${VERSION}

push.requirements:
	docker push ${AR_REPO}:${REQUIREMENTS_TAG}

push.self-hosted-release:
	docker push ${DOCKERHUB_REPO}:${release_version}_no_dependencies
	docker push ${DOCKERHUB_REPO}:latest_calver_no_dependencies
	docker push ${DOCKERHUB_REPO}:latest_stable_no_dependencies
	docker push ${DOCKERHUB_REPO}:${release_version}
	docker push ${DOCKERHUB_REPO}:latest-stable
	docker push ${DOCKERHUB_REPO}:latest-calver

push.self-hosted-rolling:
	docker push ${DOCKERHUB_REPO}:rolling_no_dependencies
	docker push ${DOCKERHUB_REPO}:rolling

shell:
	docker-compose exec worker bash

test_env.up:
	env | grep GITHUB > .testenv; true
	docker-compose up -d

test_env.prepare:
	docker-compose exec worker make test_env.container_prepare

test_env.check_db:
	docker-compose exec worker make test_env.container_check_db

test_env.install_cli:
	pip install --no-cache-dir codecov-cli==$(CODECOV_CLI_VERSION)

test_env.container_prepare:
	apt-get update
	apt-get install -y git build-essential netcat-traditional
	git config --global --add safe.directory /apps/app/worker || true

test_env.container_check_db:
	while ! nc -vz postgres 5432; do sleep 1; echo "waiting for postgres"; done
	while ! nc -vz timescale 5432; do sleep 1; echo "waiting for timescale"; done

test_env.run_unit:
	docker-compose exec worker make test.unit PYTEST_ROOTDIR=${PYTEST_ROOTDIR}

test_env.run_integration:
	docker-compose exec worker make test.integration PYTEST_ROOTDIR=${PYTEST_ROOTDIR}

test_env:
	make test_env.up
	make test_env.prepare
	make test_env.check_db
	make test_env.run_unit
	make test_env.run_integration
