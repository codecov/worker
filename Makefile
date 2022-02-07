sha := $(shell git rev-parse --short=7 HEAD)
release_version = `cat VERSION`
_gcr := gcr.io/test6u3411ty6xqh462sri/codecov
build_date ?= $(shell git show -s --date=iso8601-strict --pretty=format:%cd $$sha)
name ?= worker
branch = $(shell git branch | grep \* | cut -f2 -d' ')
gh_access_token := $(shell echo ${GH_ACCESS_TOKEN})
epoch := $(shell date +"%s")

build.local:
	docker build -f dockerscripts/Dockerfile . -t codecov/worker:latest --build-arg RELEASE_VERSION="${release_version}" --ssh default

build.base:
	DOCKER_BUILDKIT=1 docker build -f dockerscripts/Dockerfile.requirements . -t codecov/baseworker:latest --ssh default

build:
	$(MAKE) build.base
	$(MAKE) build.local

build.enterprise:
	$(MAKE) build.base
	docker build -f dockerscripts/Dockerfile.enterprise . -t codecov/enterprise-local-worker:${release_version} \
		--build-arg REQUIREMENTS_IMAGE=codecov/baseworker \
		--build-arg RELEASE_VERSION="${release_version}" \
		--label "org.label-schema.build-date"="$(build_date)" \
		--label "org.label-schema.name"="Self-Hosted Worker" \
		--label "org.label-schema.vendor"="Codecov" \
		--label "org.label-schema.version"="${release_version}" \
		--squash

# for building and pushing private images to dockerhub. This is useful if you 
# need to push a test image for enterprise to test in sandbox deployments.
build.enterprise-private: 
	docker build -f dockerscripts/Dockerfile.enterprise . -t codecov/worker-private:${release_version}-${sha} \
		--build-arg REQUIREMENTS_IMAGE=codecov/baseworker \
		--build-arg RELEASE_VERSION="${release_version}" \
		--label "org.label-schema.build-date"="$(build_date)" \
		--label "org.label-schema.name"="Self-Hosted Worker Private" \
		--label "org.label-schema.vendor"="Codecov" \
		--label "org.label-schema.version"="${release_version}-${sha}" \
		--label "org.vcs-branch"="$(branch)" \
		--squash

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
	pip install black==19.10b0 isort
	black --check .
	isort --profile black .

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

#push enterprise
push.enterprise:
	docker push codecov/enterprise-worker:${release_version}
	docker tag codecov/enterprise-worker:${release_version} codecov/enterprise-worker:latest-stable
	docker push codecov/enterprise-worker:latest-stable

update-requirements:
	pip install pip-tools==6.1.0
	pip-compile requirements.in

tag.qa-release:
	git tag -a qa-${release_version}-${sha}-${epoch} -m "Autogenerated tag for worker QA ${version}"
	git push origin qa-${release_version}-${sha}-${epoch}

tag.enterprise-release:
	git tag -a enterprise-${release_version} -m "Autogenerated release tag for enterprise worker ${version}"
	git push origin enterprise-${release_version}
