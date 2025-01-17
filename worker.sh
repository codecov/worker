#!/bin/bash

if [ -n "$PROMETHEUS_MULTIPROC_DIR" ]; then
    rm -r "$PROMETHEUS_MULTIPROC_DIR" 2> /dev/null
    mkdir "$PROMETHEUS_MULTIPROC_DIR"
fi

queues=""
if [ "$CODECOV_WORKER_QUEUES" ]; then
  queues="--queue $CODECOV_WORKER_QUEUES"
fi

if [ "$RUN_ENV" = "ENTERPRISE" ] || [ "$RUN_ENV" = "DEV" ]; then
    python manage.py migrate
    python manage.py migrate --database "timeseries"
fi

if [ "$RUN_ENV" = "DEV" ]; then
    python manage.py migrate --database "test_analytics"
fi

if [ -z "$1" ];
then
  python main.py worker ${queues}
else
  exec "$@"
fi
