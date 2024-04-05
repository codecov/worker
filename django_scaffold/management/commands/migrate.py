import logging
import time

import redis_lock
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import connections
from django.db import transaction as django_transaction
from django.db.utils import IntegrityError, ProgrammingError

from services.redis import get_redis_connection

log = logging.getLogger(__name__)

MIGRATION_LOCK_NAME = "djang-migrations-lock"


class MockLock:
    def release(self):
        pass


class Command(MigrateCommand):
    """
    We need to override the migrate command to block on acquiring a lock in Redis.
    Otherwise, concurrent worker and api deploys could attempt to run migrations
    at the same time which is not safe.

    This class is copied from `codecov-api` except it omits logic about faking
    certain migrations. When the `legacy_migrations` app is moved to `shared`
    and installed in `worker`, which is a prerequisite for core models, we can
    delete this.
    """

    def _obtain_lock(self):
        """
        In certain environments we might be running mutliple servers that will try and run the migrations at the same time. This is
        not safe to do. So we have the command obtain a lock to try and run the migration. If it cannot get a lock, it will wait
        until it is able to do so before continuing to run. We need to wait for the lock instead of hard exiting on seeing another
        server running the migrations because we write code in such a way that the server expects for migrations to be applied before
        new code is deployed (but the opposite of new db with old code is fine).
        """
        # If we're running in a non-server environment, we don't need to worry about acquiring a lock
        if settings.IS_DEV:
            return MockLock()

        redis_connection = get_redis_connection()
        lock = redis_lock.Lock(
            redis_connection, MIGRATION_LOCK_NAME, expire=180, auto_renewal=True
        )
        log.info("Trying to acquire migrations lock...")
        acquired = lock.acquire(timeout=180)

        if not acquired:
            return None

        return lock

    def handle(self, *args, **options):
        log.info("Codecov is starting migrations...")
        database = options["database"]
        db_connection = connections[database]
        options["run_syncdb"] = False

        lock = self._obtain_lock()

        # Failed to acquire lock due to timeout
        if not lock:
            log.error("Potential deadlock detected in api migrations.")
            raise Exception("Failed to obtain lock for api migration.")

        try:
            super().handle(*args, **options)

            # Autocommit is disabled in worker
            django_transaction.commit(database)
        except:
            log.info("Codecov migrations failed.")
            raise
        else:
            log.info("Codecov migrations succeeded.")
        finally:
            lock.release()
