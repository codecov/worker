FROM            codecov/baseworker


USER            codecov

ARG             RELEASE_VERSION

ENV             RELEASE_VERSION $RELEASE_VERSION

COPY            . /worker
WORKDIR         /worker
