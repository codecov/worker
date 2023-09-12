from services.smtp import get_smtp_service


class TestStorage(object):
    def test_get_storage_client(self):
        first = get_smtp_service()
        second = get_smtp_service()
        assert id(first) == id(second)
