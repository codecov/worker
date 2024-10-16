import unittest
from unittest.mock import patch, MagicMock
from helpers.checkpoint_logger.prometheus import PrometheusCheckpointLoggerHandler, PROMETHEUS_HANDLER


class TestPrometheusCheckpointLoggerHandler(unittest.TestCase):

    def setUp(self):
        self.handler = PrometheusCheckpointLoggerHandler()

    @patch('helpers.checkpoint_logger.prometheus.CHECKPOINTS_TOTAL_BEGUN')
    def test_log_begun(self, mock_begun):
        self.handler.log_begun("test_flow")
        mock_begun.labels.assert_called_once_with(flow="test_flow")
        mock_begun.labels.return_value.inc.assert_called_once()

    @patch('helpers.checkpoint_logger.prometheus.CHECKPOINTS_TOTAL_FAILED')
    def test_log_failure(self, mock_failed):
        self.handler.log_failure("test_flow")
        mock_failed.labels.assert_called_once_with(flow="test_flow")
        mock_failed.labels.return_value.inc.assert_called_once()

    @patch('helpers.checkpoint_logger.prometheus.CHECKPOINTS_TOTAL_SUCCEEDED')
    def test_log_success(self, mock_succeeded):
        self.handler.log_success("test_flow")
        mock_succeeded.labels.assert_called_once_with(flow="test_flow")
        mock_succeeded.labels.return_value.inc.assert_called_once()

    @patch('helpers.checkpoint_logger.prometheus.CHECKPOINTS_TOTAL_ENDED')
    def test_log_total_ended(self, mock_ended):
        self.handler.log_total_ended("test_flow")
        mock_ended.labels.assert_called_once_with(flow="test_flow")
        mock_ended.labels.return_value.inc.assert_called_once()

    @patch('helpers.checkpoint_logger.prometheus.CHECKPOINTS_EVENTS')
    def test_log_checkpoints(self, mock_events):
        self.handler.log_checkpoints("test_flow", "test_checkpoint")
        mock_events.labels.assert_called_once_with(flow="test_flow", checkpoint="test_checkpoint")
        mock_events.labels.return_value.inc.assert_called_once()

    @patch('helpers.checkpoint_logger.prometheus.CHECKPOINTS_ERRORS')
    def test_log_errors(self, mock_errors):
        self.handler.log_errors("test_flow")
        mock_errors.labels.assert_called_once_with(flow="test_flow")
        mock_errors.labels.return_value.inc.assert_called_once()

    @patch('helpers.checkpoint_logger.prometheus.CHECKPOINTS_SUBFLOW_DURATION')
    def test_log_subflow(self, mock_subflow_duration):
        self.handler.log_subflow("test_flow", "test_subflow", 10)
        mock_subflow_duration.labels.assert_called_once_with(flow="test_flow", subflow="test_subflow")
        mock_subflow_duration.labels.return_value.observe.assert_called_once_with(10)


class TestCheckpointLogger(unittest.TestCase):

    @patch('helpers.checkpoint_logger.PROMETHEUS_HANDLER')
    @patch('sentry_sdk.set_measurement')
    def test_submit_subflow(self, mock_set_measurement, mock_prometheus_handler):
        # We need to mock the CheckpointLogger class and its methods
        mock_checkpoint_logger = MagicMock()
        mock_checkpoint_logger.cls.__name__ = "TestFlow"

        # Mock the start and end events
        mock_start = MagicMock()
        mock_end = MagicMock()

        # Set up the mock timing
        mock_checkpoint_logger.timing.return_value = 5000  # 5 seconds in milliseconds

        # Call the submit_subflow method
        from helpers.checkpoint_logger import CheckpointLogger
        CheckpointLogger.submit_subflow(mock_checkpoint_logger, "test_metric", mock_start, mock_end)

        # Assert that sentry_sdk.set_measurement was called correctly
        mock_set_measurement.assert_called_once_with("test_metric", 5000, "milliseconds")

        # Assert that PROMETHEUS_HANDLER.log_subflow was called correctly
        mock_prometheus_handler.log_subflow.assert_called_once_with(
            flow="TestFlow", subflow="test_metric", duration=5.0
        )


if __name__ == '__main__':
    unittest.main()