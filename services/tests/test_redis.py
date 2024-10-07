from services.redis import get_redis_connection


def test_get_redis_connection(mocker):
    mocked = mocker.patch("services.redis.Redis.from_url")
    res = get_redis_connection()
    assert res is not None
    mocked.assert_called_with("redis://redis:6379")
