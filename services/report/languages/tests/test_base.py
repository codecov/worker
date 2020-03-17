from tests.base import BaseTestCase
from services.report.languages import CloverProcessor


class TestBaseProcessor(BaseTestCase):
    def test_name(self):
        assert CloverProcessor.get_processor_name() == "CloverProcessor"
