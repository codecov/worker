import asyncio
import hashlib
import base64
import logging
import pickle

from redis import RedisError

from functools import wraps
from helpers.metrics import metrics

log = logging.getLogger(__name__)

NO_VALUE = object()


def make_hash_sha256(o):
    hasher = hashlib.sha256()
    hasher.update(repr(make_hashable(o)).encode())
    return base64.b64encode(hasher.digest()).decode()


def make_hashable(o):
    if isinstance(o, (tuple, list)):
        return tuple((make_hashable(e) for e in o))
    if isinstance(o, dict):
        return tuple(sorted((k, make_hashable(v)) for k, v in o.items()))
    if isinstance(o, (set, frozenset)):
        return tuple(sorted(make_hashable(e) for e in o))
    return o


class BaseBackend(object):

    def get(self, key):
        raise NotImplementedError()

    def set(self, key, value):
        raise NotImplementedError()


class NullBackend(BaseBackend):
    def get(self, key):
        return NO_VALUE

    def set(self, key, value):
        pass


class RedisBackend(BaseBackend):
    def __init__(self, redis_connection, expiration_time):
        log.info("Initializing redis cache")
        self.redis_connection = redis_connection
        self.expiration_time = expiration_time

    def get(self, key):
        try:
            serialized_value = self.redis_connection.get(key)
        except RedisError:
            log.warning("Unable to fetch from cache on redis", exc_info=True)
            return NO_VALUE
        if serialized_value is None:
            return NO_VALUE
        return pickle.loads(serialized_value)

    def set(self, key, value):
        serialized_value = pickle.dumps(value, pickle.HIGHEST_PROTOCOL)
        try:
            self.redis_connection.setex(key, self.expiration_time, serialized_value)
        except RedisError:
            log.warning("Unable to set cache on redis", exc_info=True)


class OurOwnCache(object):
    def __init__(self):
        self._backend = NullBackend()

    def configure(self, backend):
        self._backend = backend

    def get_backend(self):
        return self._backend

    def cache_function(self, func):
        if asyncio.iscoroutinefunction(func):
            return self.cache_async_function(func)
        return self.cache_synchronous_function(func)

    def cache_synchronous_function(self, func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            key = self.generate_key(func, args, kwargs)
            value = self.get_backend().get(key)
            if value is not NO_VALUE:
                metrics.incr(f"new_worker.caches.{func.__name__}.hits")
                return value
            metrics.incr(f"new_worker.caches.{func.__name__}.misses")
            with metrics.timer(f"new_worker.caches.{func.__name__}.runtime"):
                result = func(*args, **kwargs)
            self.get_backend().set(key, result)
            return result

        return wrapped

    def generate_key(self, func, args, kwargs):
        func_name = make_hash_sha256(func.__name__)
        tupled_args = make_hash_sha256(args)
        frozen_kwargs = make_hash_sha256(kwargs)
        return ":".join(["cache", func_name, tupled_args, frozen_kwargs])

    def cache_async_function(self, func):
        @wraps(func)
        async def wrapped(*args, **kwargs):
            key = self.generate_key(func, args, kwargs)
            value = self.get_backend().get(key)
            if value is not NO_VALUE:
                metrics.incr(f"new_worker.caches.{func.__name__}.hits")
                return value
            metrics.incr(f"new_worker.caches.{func.__name__}.misses")
            with metrics.timer(f"new_worker.caches.{func.__name__}.runtime"):
                result = await func(*args, **kwargs)
            self.get_backend().set(key, result)
            return result

        return wrapped


cache = OurOwnCache()
