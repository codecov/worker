#!/bin/sh

queues=""
if [[ "$CODECOV_WORKER_QUEUES" ]]; then
  queues="--queue $CODECOV_WORKER_QUEUES"
fi

if [ -z "$1" ];
then
  if [ "$WORKER_HOT_RELOAD" = "y" ]
  then
    watchmedo auto-restart --patterns="*.py;*.sh" --recursive --signal=SIGTERM python main.py worker ${queues}
  else
    python main.py worker ${queues}
  fi
else
  exec "$@"
fi