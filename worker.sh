#!/bin/sh

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