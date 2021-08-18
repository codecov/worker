from services.redis import get_redis_connection
from tests.base import BaseTestCase


class TestRedis(BaseTestCase):
    def test_get_redis_connection(self, mocker, mock_configuration):
        mocked = mocker.patch("services.redis.Redis.from_url")
        res = get_redis_connection()
        assert res is not None
        mocked.assert_called_with("redis://redis:@localhost:6379/")
