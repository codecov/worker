from services.report.languages import CloverProcessor
from test_utils.base import BaseTestCase


class TestBaseProcessor(BaseTestCase):
    def test_name(self):
        assert CloverProcessor.get_processor_name() == "CloverProcessor"
