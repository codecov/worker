from services.smtp import get_smtp_service


class TestStorage(object):
    # need to have this use the mock_configuration fixture so
    # it starts the service with the correct settings
    # so that if the integration tests are run afterwards
    # the SMTPService in those has the correct settings
    def test_get_storage_client(self, mock_configuration):
        first = get_smtp_service()
        second = get_smtp_service()
        assert id(first) == id(second)

    def test_idempotent_open(self, mocker, mock_configuration):
        mocker.patch("smtplib.SMTP")
        service = get_smtp_service()
        service.open()
        first = service._conn
        service.open()
        second = service._conn
        assert id(first) == id(second)

    def test_idempotent_close(self, mocker, mock_configuration):
        mocker.patch("smtplib.SMTP")
        service = get_smtp_service()
        service.close()
        assert service._conn == None
        service.close()
        assert service._conn == None
