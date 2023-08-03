#!/bin/bash

patterns='--patterns="*.py;*.sh"'
ignores=''

if [ "$EDITABLE_SHARED" = "y" ]
then
    # Install shared "editably" so that the installed module maps back to the in-tree source
    pip install -e ./shared
    watchmedo auto-restart --patterns="*.py;*.sh" --recursive --signal=SIGTERM sh worker.sh
else
    # Not using the editable shared install, so changes to shared shouldn't trigger hot-reloading
    watchmedo auto-restart --patterns="*.py;*.sh" --ignore-pattern="shared/*;shared/**/*" --recursive --signal=SIGTERM sh worker.sh
fi

