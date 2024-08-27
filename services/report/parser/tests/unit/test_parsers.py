import pytest

from database.tests.factories import UploadFactory
from services.report.parser import (
    LegacyReportParser,
    VersionOneReportParser,
    get_proper_parser,
)


@pytest.mark.parametrize(
    "upload_extras, contents, expected_type",
    [
        (None, b"", LegacyReportParser),
        ({}, b"", LegacyReportParser),
        ({"something": 1}, b"", LegacyReportParser),
        ({"format_version": "v1"}, b"{}", VersionOneReportParser),
        ({"format_version": "v1", "something": "else"}, b"{}", VersionOneReportParser),
        ({"format_version": None}, b"", LegacyReportParser),
        ({"format_version": "v1"}, b"not/a/v1/format.txt", LegacyReportParser),
    ],
)
def test_get_proper_parser(dbsession, upload_extras, contents, expected_type):
    upload = UploadFactory.create(upload_extras=upload_extras)
    dbsession.add(upload)
    dbsession.flush()
    assert isinstance(get_proper_parser(upload, contents), expected_type)
