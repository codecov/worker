# syntax=docker/dockerfile:1.4
ARG REQUIREMENTS_IMAGE
ARG BUILD_ENV=self-hosted
ARG BERGLAS_VERSION=2.0.6

FROM us-docker.pkg.dev/berglas/berglas/berglas:$BERGLAS_VERSION as berglas


FROM $REQUIREMENTS_IMAGE as app
WORKDIR /app-dir
ADD . /app-dir
RUN chmod +x worker.sh
ARG RELEASE_VERSION
ENV RELEASE_VERSION=$RELEASE_VERSION
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python \
    UV_PROJECT_ENVIRONMENT=/worker
ENTRYPOINT ["./worker.sh"]


FROM app as local


FROM app as cloud
COPY --chmod=755 --from=berglas /bin/berglas /usr/local/bin/berglas


FROM app as self-hosted
ENV RUN_ENV="ENTERPRISE"


FROM self-hosted as self-hosted-runtime
USER root
ARG EXTERNAL_DEPS_FOLDER=./external_deps
RUN mkdir $EXTERNAL_DEPS_FOLDER
RUN pip install --target $EXTERNAL_DEPS_FOLDER psycopg2-binary tlslite-ng
RUN chown codecov:application $EXTERNAL_DEPS_FOLDER
USER codecov


FROM ${BUILD_ENV}