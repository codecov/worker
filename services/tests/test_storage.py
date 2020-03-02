from services.storage import get_storage_client, get_appropriate_storage_service


class TestStorage(object):

    def test_get_storage_client(self):
        first = get_storage_client()
        second = get_storage_client()
        assert id(first) == id(second)
        another_one = get_appropriate_storage_service()
        assert id(first) != id(another_one)
        assert id(second) != id(another_one)
