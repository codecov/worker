#!/bin/sh

echo "Running Timeseries Django migrations"
prefix=""
if [ -f "/usr/local/bin/berglas" ]; then
  prefix="berglas exec --"
fi

$prefix python manage.py migrate --database timeseries rollouts
$prefix python manage.py migrate --database timeseries pg_telemetry
