import asyncio
import hashlib
import base64
import logging
import pickle
from typing import Any, Callable, Hashable

from redis import RedisError, Redis

from functools import wraps
from helpers.metrics import metrics

log = logging.getLogger(__name__)

NO_VALUE = object()

DEFAULT_TTL = 120


def make_hash_sha256(o: Any) -> str:
    """Provides a machine-independent, consistent hash value for any object

    Args:
        o (Any): Any object we want

    Returns:
        str: a sha256-based hash that is always the same for the same object
    """
    hasher = hashlib.sha256()
    hasher.update(repr(make_hashable(o)).encode())
    return base64.b64encode(hasher.digest()).decode()


def make_hashable(o: Any) -> Hashable:
    """
        Converts any object into an object that will have a consistent hash
    """
    if isinstance(o, (tuple, list)):
        return tuple((make_hashable(e) for e in o))
    if isinstance(o, dict):
        return tuple(sorted((k, make_hashable(v)) for k, v in o.items()))
    if isinstance(o, (set, frozenset)):
        return tuple(sorted(make_hashable(e) for e in o))
    return o


class BaseBackend(object):
    """
        This is the interface a class needs to honor in order to work as a backend.

        The only two needed functions are `get` and `set`, which will fetch information from the
            cache and send information to it, respectively.

        However the cache wants to work internally, it's their choice. They only need to be able to
            `set` and `get` without raising any exceptions
    """
    def get(self, key: str) -> Any:
        """Returns a cached value from the cache, or NO_VALUE, if no cache is set for that key

        Args:
            key (str): The key that represents the objecr

        Returns:
            Any: The object that is possibly cached, or NO_VALUE, if no cache was there
        """
        raise NotImplementedError()

    def set(self, key: str, ttl: int, value: Any):
        raise NotImplementedError()


class NullBackend(BaseBackend):
    """
        This is the default implementation of BaseBackend that is used.

        It essentially `gets` as if nothing is cached, and does not cache anything when requested
            to.

        This makes the cache virtually transparent. It acts as if no cache was there
    """
    def get(self, key: str):
        return NO_VALUE

    def set(self, key: str, ttl: int, value: Any):
        pass


class RedisBackend(BaseBackend):
    def __init__(self, redis_connection: Redis):
        self.redis_connection = redis_connection

    def get(self, key: str) -> Any:
        try:
            serialized_value = self.redis_connection.get(key)
        except RedisError:
            log.warning("Unable to fetch from cache on redis", exc_info=True)
            return NO_VALUE
        if serialized_value is None:
            return NO_VALUE
        return pickle.loads(serialized_value)

    def set(self, key: str, ttl: int, value: Any):
        serialized_value = pickle.dumps(value, pickle.HIGHEST_PROTOCOL)
        try:
            self.redis_connection.setex(key, ttl, serialized_value)
        except RedisError:
            log.warning("Unable to set cache on redis", exc_info=True)


class OurOwnCache(object):
    """
        This is codecov distributed cache's implementation.

        The tldr to use it is, given a function f:

        ```
        from helpers.cache import cache

        @cache.cache_function()
        def f(...):
            ...
        ```

        Now to explain its internal workings.

        This is a configurable-at-runtime cache. Its whole idea is based on the fact that it does
            not need information at import-time. This allows us to use it transparently and still
            not have to change tests, for example, due to it. All tests occur as if the cache was
            not there.

        All that is needed to configure the backend is to do

        ```
        cache.configure(any_backend)
        ```

        which we currently do at `worker_process_init` time with a RedisBackend instance. Other
            instances can be plugged in easily, once needed. A backend is any implementation
            of `BaseBackend`, which is described at their docstrings.

        When `cache.cache_function()` is called, a `FunctionCacher` is returned. They do the heavy
            lifting of actually decorating the function properly, dealign with sync-async context.

    """
    def __init__(self):
        self._backend = NullBackend()

    def configure(self, backend: BaseBackend):
        self._backend = backend

    def get_backend(self) -> BaseBackend:
        return self._backend

    def cache_function(self, ttl: int = DEFAULT_TTL) -> "FunctionCacher":
        """Creates a FunctionCacher with all the needed configuration to cache a function

        Args:
            ttl (int, optional): The time-to-live of the cache

        Returns:
            FunctionCacher: A FunctionCacher that can decorate any callable
        """
        return FunctionCacher(self, ttl)


class FunctionCacher(object):
    def __init__(self, cache_instance: OurOwnCache, ttl: int):
        self.cache_instance = cache_instance
        self.ttl = ttl

    def __call__(self, func):
        if asyncio.iscoroutinefunction(func):
            return self.cache_async_function(func)
        return self.cache_synchronous_function(func)

    def cache_synchronous_function(self, func: Callable):
        @wraps(func)
        def wrapped(*args, **kwargs):
            key = self.generate_key(func, args, kwargs)
            value = self.cache_instance.get_backend().get(key)
            if value is not NO_VALUE:
                metrics.incr(f"new_worker.caches.{func.__name__}.hits")
                return value
            metrics.incr(f"new_worker.caches.{func.__name__}.misses")
            with metrics.timer(f"new_worker.caches.{func.__name__}.runtime"):
                result = func(*args, **kwargs)
            self.cache_instance.get_backend().set(key, self.ttl, result)
            return result

        return wrapped

    def generate_key(self, func, args, kwargs):
        func_name = make_hash_sha256(func.__name__)
        tupled_args = make_hash_sha256(args)
        frozen_kwargs = make_hash_sha256(kwargs)
        return ":".join(["cache", func_name, tupled_args, frozen_kwargs])

    def cache_async_function(self, func: Callable):
        @wraps(func)
        async def wrapped(*args, **kwargs):
            key = self.generate_key(func, args, kwargs)
            value = self.cache_instance.get_backend().get(key)
            if value is not NO_VALUE:
                metrics.incr(f"new_worker.caches.{func.__name__}.hits")
                return value
            metrics.incr(f"new_worker.caches.{func.__name__}.misses")
            with metrics.timer(f"new_worker.caches.{func.__name__}.runtime"):
                result = await func(*args, **kwargs)
            self.cache_instance.get_backend().set(key, self.ttl, result)
            return result

        return wrapped


cache = OurOwnCache()
