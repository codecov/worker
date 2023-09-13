sha := $(shell git rev-parse --short=7 HEAD)
full_sha := $(shell git rev-parse HEAD)
release_version = `cat VERSION`
_gcr := ${CODECOV_WORKER_GCR_REPO_BASE}

build_date ?= $(shell git show -s --date=iso8601-strict --pretty=format:%cd $$sha)
name ?= worker
branch = $(shell git branch | grep \* | cut -f2 -d' ')
gh_access_token := $(shell echo ${GH_ACCESS_TOKEN})
epoch := $(shell date +"%s")

AR_REPO ?= codecov/worker
DOCKERHUB_REPO ?= codecov/self-hosted-worker
REQUIREMENTS_TAG := requirements-v1-$(shell sha1sum requirements.txt | cut -d ' ' -f 1)-$(shell sha1sum docker/Dockerfile.requirements | cut -d ' ' -f 1)
VERSION := release-${sha}
CODECOV_UPLOAD_TOKEN ?= "notset"
CODECOV_STATIC_TOKEN ?= "notset"
CODECOV_URL ?= "https://api.codecov.io"
export DOCKER_BUILDKIT=1
export WORKER_DOCKER_REPO=${AR_REPO}
export WORKER_DOCKER_VERSION=${VERSION}
export CODECOV_TOKEN=${CODECOV_UPLOAD_TOKEN}

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

lint:
	make lint.install
	make lint.run

test:
	python -m pytest --cov=./

test.unit:
	python -m pytest --cov=./ -m "not integration" --cov-report=xml:unit.coverage.xml

test.integration:
	python -m pytest --cov=./ -m "integration" --cov-report=xml:integration.coverage.xml


update-requirements:
	pip install pip-tools==6.1.0
	pip-compile requirements.in


lint.install:
	echo "Installing..."
	pip install -Iv black==22.3.0 isort

lint.run:
	black .
	isort --profile black .

lint.check:
	echo "Linting..."
	black --check .
	echo "Sorting..."
	isort --profile black --check .

build.requirements:
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
		--build-arg REQUIREMENTS_IMAGE=${AR_REPO}:${REQUIREMENTS_TAG} \
		--build-arg RELEASE_VERSION=${VERSION} \
		--build-arg BUILD_ENV=cloud

build.self-hosted:
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

tag.self-hosted:
	docker tag ${DOCKERHUB_REPO}:${VERSION}-no-dependencies ${DOCKERHUB_REPO}:${release_version}_no_dependencies
	docker tag ${DOCKERHUB_REPO}:${VERSION}-no-dependencies ${DOCKERHUB_REPO}:latest_calver_no_dependencies
	docker tag ${DOCKERHUB_REPO}:${VERSION}-no-dependencies ${DOCKERHUB_REPO}:latest_stable_no_dependencies
	docker tag ${DOCKERHUB_REPO}:${VERSION} ${DOCKERHUB_REPO}:${release_version}
	docker tag ${DOCKERHUB_REPO}:${VERSION} ${DOCKERHUB_REPO}:latest-stable
	docker tag ${DOCKERHUB_REPO}:${VERSION} ${DOCKERHUB_REPO}:latest-calver

load.requirements:
	docker load --input requirements.tar
	docker tag codecov/worker-ci-requirements:${REQUIREMENTS_TAG} ${AR_REPO}:${REQUIREMENTS_TAG}

save.app:
	docker save -o app.tar ${AR_REPO}:${VERSION}

save.requirements:
	docker tag ${AR_REPO}:${REQUIREMENTS_TAG} codecov/worker-ci-requirements:${REQUIREMENTS_TAG}
	docker save -o requirements.tar codecov/worker-ci-requirements:${REQUIREMENTS_TAG}

save.self-hosted:
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

push.self-hosted:
	docker push ${DOCKERHUB_REPO}:${release_version}_no_dependencies
	docker push ${DOCKERHUB_REPO}:latest_calver_no_dependencies
	docker push ${DOCKERHUB_REPO}:latest_stable_no_dependencies
	docker push ${DOCKERHUB_REPO}:${release_version}
	docker push ${DOCKERHUB_REPO}:latest-stable
	docker push ${DOCKERHUB_REPO}:latest-calver

push.self-hosted-rolling:
	docker push ${DOCKERHUB_REPO}:rolling_no_dependencies
	docker push ${DOCKERHUB_REPO}:rolling

test_env.up:
	env | grep GITHUB > .testenv; true
	TIMESERIES_ENABLED=${TIMESERIES_ENABLED} docker-compose -f docker-compose-test.yml up -d

test_env.prepare:
	docker-compose -f docker-compose-test.yml exec worker make test_env.container_prepare

test_env.check_db:
	docker-compose -f docker-compose-test.yml exec worker make test_env.container_check_db

test_env.install_cli:
	pip install --no-cache-dir codecov-cli

test_env.container_prepare:
	apk add -U curl git build-base
	make test_env.install_cli
	git config --global --add safe.directory /worker

test_env.container_check_db:
	while ! nc -vz postgres 5432; do sleep 1; echo "waiting for postgres"; done
	while ! nc -vz timescale 5432; do sleep 1; echo "waiting for timescale"; done

test_env.run_unit:
	docker-compose -f docker-compose-test.yml exec worker make test.unit

test_env.run_integration:
	docker-compose -f docker-compose-test.yml exec worker make test.integration

test_env.upload:
	docker-compose -f docker-compose-test.yml exec worker make test_env.container_upload_custom_url CODECOV_UPLOAD_TOKEN=${CODECOV_UPLOAD_TOKEN} CODECOV_URL=${CODECOV_URL}

test_env.container_upload:
	codecovcli -u ${CODECOV_URL} do-upload --flag latest-uploader-overall
	codecovcli -u ${CODECOV_URL} do-upload --flag unit --file unit.coverage.xml
	codecovcli -u ${CODECOV_URL} do-upload --flag integration --file integration.coverage.xml

test_env.static_analysis:
	docker-compose -f docker-compose-test.yml exec worker make test_env.container_static_analysis CODECOV_STATIC_TOKEN=${CODECOV_STATIC_TOKEN}

test_env.label_analysis:
	docker-compose -f docker-compose-test.yml exec worker make test_env.container_label_analysis CODECOV_STATIC_TOKEN=${CODECOV_STATIC_TOKEN}

test_env.ats:
	docker-compose -f docker-compose-test.yml exec worker make test_env.container_ats CODECOV_UPLOAD_TOKEN=${CODECOV_UPLOAD_TOKEN}

test_env.container_static_analysis:
	codecovcli static-analysis --token=${CODECOV_STATIC_TOKEN}

test_env.container_label_analysis:
	codecovcli label-analysis --base-sha=$(shell git merge-base HEAD^ origin/main) --token=${CODECOV_STATIC_TOKEN}

test_env.container_ats:
	codecovcli --codecov-yml-path=codecov_cli.yml do-upload --plugin pycoverage --plugin compress-pycoverage --flag onlysomelabels --fail-on-error

test_env.run_mutation:
	docker-compose -f docker-compose-test.yml exec worker make test_env.container_mutation

test_env.container_mutation:
	apk add git
	git diff origin/main ${full_sha} > data.patch
	pip install mutmut[patch]
	mutmut run --use-patch-file data.patch || true
	mkdir /tmp/artifacts;
	mutmut junitxml > /tmp/artifacts/mut.xml

test_env:
	make test_env.up
	make test_env.prepare
	make test_env.check_db
	make test_env.run_unit
	make test_env.run_integration