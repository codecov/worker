from tests.base import BaseTestCase
from services.redis import get_redis_connection


class TestRedis(BaseTestCase):

    def test_get_redis_connection(self, mocker):
        mocked = mocker.patch('services.redis.Redis.from_url')
        res = get_redis_connection()
        assert res is not None
        mocked.assert_called_with('redis://redis:@localhost:6379/')
