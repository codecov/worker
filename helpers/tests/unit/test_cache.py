import pickle

import pytest
from redis.exceptions import TimeoutError

from helpers.cache import (
    NO_VALUE,
    BaseBackend,
    OurOwnCache,
    RedisBackend,
    make_hash_sha256,
)


class RandomCounter(object):
    def __init__(self):
        self.value = 0

    def call_function(self):
        self.value += 1
        return self.value

    async def async_call_function(self):
        self.value += 2
        self.value *= 4
        return self.value


class FakeBackend(BaseBackend):
    def __init__(self):
        self.all_keys = {}

    def get(self, key):
        possible_values = self.all_keys.get(key, {})
        for ttl, val in possible_values.items():
            return val
        return NO_VALUE

    def set(self, key, ttl, value):
        if key not in self.all_keys:
            self.all_keys[key] = {}
        self.all_keys[key][ttl] = value


class FakeRedis(object):
    def __init__(self):
        self.all_keys = {}

    def get(self, key):
        return self.all_keys.get(key)

    def setex(self, key, expire, value):
        self.all_keys[key] = value


class FakeRedisWithIssues(object):
    def get(self, key):
        raise TimeoutError()

    def setex(self, key, expire, value):
        raise TimeoutError()


class TestRedisBackend(object):
    def test_simple_redis_call(self):
        redis_backend = RedisBackend(FakeRedis())
        assert redis_backend.get("normal_key") == NO_VALUE
        redis_backend.set("normal_key", 120, {"value_1": set("ascdefgh"), 1: [1, 3]})
        assert redis_backend.get("normal_key") == {
            "value_1": set("ascdefgh"),
            1: [1, 3],
        }

    def test_simple_redis_call_invalid_pickle_version(self):
        redis_instance = FakeRedis()
        # PICKLE HERE WILL BE SET TO VERSION 9 (\x09 in the second byte of the value)
        # IF THIS STOPS FAILING WITH ValueError, CHANGE THE SECOND BYTE TO SOMETHING HIGHER
        redis_instance.setex("key", 120, b"\x80\x09X\x05\x00\x00\x00valueq\x00.")
        redis_backend = RedisBackend(redis_instance)
        assert redis_backend.get("key") == NO_VALUE

    def test_simple_redis_call_exception(self):
        redis_backend = RedisBackend(FakeRedisWithIssues())
        assert redis_backend.get("normal_key") == NO_VALUE
        redis_backend.set("normal_key", 120, {"value_1": set("ascdefgh"), 1: [1, 3]})
        assert redis_backend.get("normal_key") == NO_VALUE


class TestCache(object):
    def test_simple_caching_no_backend_no_params(self, mocker):
        cache = OurOwnCache()
        sample_function = RandomCounter().call_function
        cached_function = cache.cache_function()(sample_function)
        assert cached_function() == 1
        assert cached_function() == 2
        assert cached_function() == 3

    def test_simple_caching_no_backend_no_params_with_ttl(self, mocker):
        cache = OurOwnCache()
        sample_function = RandomCounter().call_function
        cached_function = cache.cache_function(ttl=300)(sample_function)
        assert cached_function() == 1
        assert cached_function() == 2
        assert cached_function() == 3

    @pytest.mark.asyncio
    async def test_simple_caching_no_backend_async_no_params(self, mocker):
        cache = OurOwnCache()
        sample_function = RandomCounter().async_call_function
        cached_function = cache.cache_function()(sample_function)
        assert (await cached_function()) == 8
        assert (await cached_function()) == 40
        assert (await cached_function()) == 168

    def test_simple_caching_fake_backend_no_params(self, mocker):
        cache = OurOwnCache()
        cache.configure(FakeBackend())
        sample_function = RandomCounter().call_function
        cached_function = cache.cache_function()(sample_function)
        assert cached_function() == 1
        assert cached_function() == 1
        assert cached_function() == 1

    @pytest.mark.asyncio
    async def test_simple_caching_fake_backend_async_no_params(self, mocker):
        cache = OurOwnCache()
        cache.configure(FakeBackend())
        sample_function = RandomCounter().async_call_function
        cached_function = cache.cache_function()(sample_function)
        assert (await cached_function()) == 8
        assert (await cached_function()) == 8
        assert (await cached_function()) == 8

    @pytest.mark.asyncio
    async def test_make_hash_sha256(self):
        assert make_hash_sha256(1) == "a4ayc/80/OGda4BO/1o/V0etpOqiLx1JwB5S3beHW0s="
        assert (
            make_hash_sha256("somestring")
            == "l5nfZJ7iQAll9QGKjGm4wPuSgUoikOMrdpOw/36GLyw="
        )
        this_set = set(["1", "something", "True", "another_string_of_values"])
        assert (
            make_hash_sha256(this_set) == "siFp5vd4+aI5SxlURDMV3Z5Yfn5qnpSbCctIewE6m44="
        )
        this_set.add("ooops")
        assert (
            make_hash_sha256(this_set) == "aoU2Of3YNk0/iW1hqfSkXPbhIAzGMHCSCoxsiLI2b8U="
        )
