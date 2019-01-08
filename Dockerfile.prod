FROM python:3.6-alpine

RUN apk add --no-cache --virtual .build-deps autoconf gcc git
COPY . app

WORKDIR app

ENV C_FORCE_ROOT true
RUN pip install -r requirements.txt

ENTRYPOINT celery -A tasks worker --loglevel=info
