import logging
import logging.config
import os

import django
from celery import Celery, signals

import database.events
from helpers.logging_config import get_logging_config_dict
from helpers.sentry import initialize_sentry, is_sentry_enabled

log = logging.getLogger(__name__)

_config_dict = get_logging_config_dict()
logging.config.dictConfig(_config_dict)

# ALERT ALERT ALERT! This is not to be done lightly!
# Django's ORM raises errors if run from within an asyncio event loop. Our
# base celery task runs all task implementations via asyncio.run(), so when
# we use Django's ORM in most of worker it'll get steamed. However, the base
# task use of asyncio is actually superfluous. Consider the following:
#
#    async def run_async():
#        await foo()
#        await bar()
#        await baz()
#    asyncio.run(run_async())
#
# `run_async()` is effectively running `foo()`, `bar()`, and `baz()`
# synchronously. When we `await foo()`, there's nothing else running in the
# event loop that we could resume, and we can't start `bar()` until `foo()`
# has completed. So... there's nothing to do but wait.
#
# With that in mind, we should be able to safely disable Django's
# protections with this environment variable.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

# we're moving this before we create the Celery object
# so that celery can detect Django is being used
# using the Django fixup will help fix some database issues
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_scaffold.settings")
django.setup()

celery_app = Celery("tasks")
celery_app.config_from_object("celery_config:CeleryWorkerConfig")


@signals.celeryd_init.connect
def init_sentry(**_kwargs):
    if is_sentry_enabled():
        initialize_sentry()
