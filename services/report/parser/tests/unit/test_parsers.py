import pytest

from database.tests.factories import UploadFactory
from services.report.parser import (
    LegacyReportParser,
    VersionOneReportParser,
    get_proper_parser,
)


@pytest.mark.parametrize(
    "upload_extras, expected_type",
    [
        (None, LegacyReportParser),
        ({}, LegacyReportParser),
        ({"something": 1}, LegacyReportParser),
        ({"format_version": "v1"}, VersionOneReportParser),
        ({"format_version": "v1", "something": "else"}, VersionOneReportParser),
        ({"format_version": None}, LegacyReportParser),
    ],
)
def test_get_proper_parser(dbsession, upload_extras, expected_type):
    upload = UploadFactory.create(upload_extras=upload_extras)
    dbsession.add(upload)
    dbsession.flush()
    assert isinstance(get_proper_parser(upload), expected_type)
