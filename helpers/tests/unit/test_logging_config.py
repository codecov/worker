from helpers.environment import Environment
from helpers.log_context import LogContext, set_log_context
from helpers.logging_config import (
    CustomLocalJsonFormatter,
    config_dict,
    get_logging_config_dict,
)


class TestLoggingConfig(object):
    def test_local_formatter(self):
        log_record = {"levelname": "weird_level", "message": "This is a message"}
        cljf = CustomLocalJsonFormatter()
        res = cljf.jsonify_log_record(log_record)
        assert "weird_level: This is a message \n {}" == res

    def test_local_formatter_with_exc_info(self):
        log_record = {
            "levelname": "weird_level",
            "message": "This is a message",
            "exc_info": "Line\nWith\nbreaks",
        }
        cljf = CustomLocalJsonFormatter()
        res = cljf.jsonify_log_record(log_record)
        assert "weird_level: This is a message \n {}\nLine\nWith\nbreaks" == res

    def test_get_logging_config_dict(self, mocker):
        get_current_env = mocker.patch("helpers.logging_config.get_current_env")
        get_current_env.return_value = Environment.production
        assert get_logging_config_dict() == config_dict

    def test_add_fields_empty_log_context(self, mocker):
        set_log_context(LogContext())
        log_record, record, message_dict = {}, mocker.MagicMock(), {"message": "aaa"}
        log_formatter = CustomLocalJsonFormatter()
        log_formatter.add_fields(log_record, record, message_dict)
        assert log_record == {
            "message": "aaa",
            "method_calls": [],
            "context": LogContext().as_dict(),
        }

    def test_add_fields_populated_log_context(self, mocker):
        log_context = LogContext(
            task_name="lkjhg", task_id="abcdef", repo_id=5, owner_id=3
        )
        set_log_context(log_context)

        log_record, record, message_dict = {}, mocker.MagicMock(), {"message": "aaa"}
        log_formatter = CustomLocalJsonFormatter()
        log_formatter.add_fields(log_record, record, message_dict)

        assert log_record == {
            "message": "aaa",
            "method_calls": [],
            "context": log_context.as_dict(),
        }
