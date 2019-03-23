# BUILD STAGE - Download dependencies from GitHub that require SSH access
FROM python:3.6-alpine as build

RUN apk update \
    && apk add --update --no-cache \
    git \
    openssh \
    postgresql-dev \
    musl-dev \
    libxslt-dev \
    python-dev \
    gcc \
    && pip install --upgrade pip

ARG SSH_PRIVATE_KEY
RUN echo ${SSH_PRIVATE_KEY}
RUN mkdir /root/.ssh/
RUN echo "${SSH_PRIVATE_KEY}" > /root/.ssh/id_rsa
RUN ssh-keyscan -H github.com >> /root/.ssh/known_hosts
RUN chmod 600 /root/.ssh/id_rsa
RUN git config --global url."git@github.com:".insteadOf "https://github.com/"

RUN mkdir -p /app
VOLUME ["/app"]
WORKDIR /app
COPY ./requirements.txt   ./app/requirements.txt
RUN pip install -r ./app/requirements.txt
COPY . /app

ENTRYPOINT ["./worker.sh"]
