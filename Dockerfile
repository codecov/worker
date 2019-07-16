# BUILD STAGE - Download dependencies from GitHub that require SSH access
FROM python:3.6-alpine as build

RUN             apk update \
                && apk add --update --no-cache \
                git \
                openssh \
                postgresql-dev \
                musl-dev \
                libxslt-dev \
                python-dev \
                gcc \
                && pip install --upgrade pip

ARG             GH_ACCESS_TOKEN

COPY            requirements.txt /
RUN             sed -i 's/github.com/'"${GH_ACCESS_TOKEN}"'@github.com/g' /requirements.txt
WORKDIR         /pip-packages/
RUN             git config --global url."git@github.com:".insteadOf "https://github.com/"
RUN             pip download -r /requirements.txt




# RUNTIME STAGE - Copy packages from build stage and install runtime dependencies
FROM            python:3.6-alpine

RUN             apk add --no-cache postgresql-libs && \
                apk add --no-cache --virtual .build-deps gcc \ 
                musl-dev \ 
                postgresql-dev \
                libxslt-dev \
                python-dev \ 
                python3-dev

WORKDIR         /pip-packages/
COPY            --from=build /pip-packages/ /pip-packages/

RUN             rm -rf /pip-packages/src
RUN             pip install --no-index --find-links=/pip-packages/ /pip-packages/*

COPY            . /app
WORKDIR         /app

COPY            codecov.yml /config/codecov.yml
