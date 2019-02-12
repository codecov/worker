from unittest.mock import MagicMock

from services.repository import get_repo


class TestRepositoryServiceTestCase(object):

    def test_get_repo(self, dbsession):
        redis_connection = MagicMock(get=MagicMock(return_value=None))
        repoid = 745206
        res = get_repo(dbsession, redis_connection, repoid)
        assert res is None
