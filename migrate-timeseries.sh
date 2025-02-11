#!/bin/sh

echo "Running Timeseries Django migrations"
prefix=""
if [ -f "/usr/local/bin/berglas" ]; then
  prefix="berglas exec --"
fi

$prefix python migrate_timeseries.py
