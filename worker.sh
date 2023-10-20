#!/bin/sh

if [ -n "$PROMETHEUS_MULTIPROC_DIR" ]; then
    rm -r "$PROMETHEUS_MULTIPROC_DIR" 2> /dev/null
    mkdir "$PROMETHEUS_MULTIPROC_DIR"
fi

queues=""
if [[ "$CODECOV_WORKER_QUEUES" ]]; then
  queues="--queue $CODECOV_WORKER_QUEUES"
fi

if [ -z "$1" ];
then
  python main.py worker ${queues}
else
  exec "$@"
fi
