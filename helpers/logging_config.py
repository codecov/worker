import json
from copy import deepcopy

from pythonjsonlogger.jsonlogger import JsonFormatter

from helpers.environment import Environment, get_current_env
from helpers.log_context import get_log_context


class BaseLogger(JsonFormatter):
    def add_fields(self, log_record, record, message_dict) -> None:
        super(BaseLogger, self).add_fields(log_record, record, message_dict)

        log_context = get_log_context()
        log_context.add_to_log_record(log_record)

    def format_json_on_new_lines(self, json_str):
        # Parse the input JSON string
        data = json.loads(json_str)

        for key, value in data.items():
            if isinstance(value, list) and len(value) > 10:
                # If more than 10 elements in a list, concat to single line
                data[key] = ", ".join(map(str, value))

        # Convert the parsed JSON data back to a formatted JSON string
        formatted_json = json.dumps(data, indent=4)
        return formatted_json


class CustomLocalJsonFormatter(BaseLogger):
    def jsonify_log_record(self, log_record) -> str:
        """Returns a json string of the log record."""
        levelname = log_record.pop("levelname")
        message = log_record.pop("message")
        exc_info = log_record.pop("exc_info", "")
        content = super().jsonify_log_record(log_record)
        formatted = super().format_json_on_new_lines(content) if content else None
        if exc_info:
            return f"{levelname}: {message} \n {formatted}\n{exc_info}"
        return f"{levelname}: {message} \n {formatted}"


class CustomDatadogJsonFormatter(BaseLogger):
    def add_fields(self, log_record, record, message_dict):
        super(CustomDatadogJsonFormatter, self).add_fields(
            log_record, record, message_dict
        )
        if not log_record.get("logger.name") and log_record.get("name"):
            log_record["logger.name"] = log_record.get("name")
        if not log_record.get("logger.thread_name") and log_record.get("threadName"):
            log_record["logger.thread_name"] = log_record.get("threadName")
        if log_record.get("level"):
            log_record["level"] = log_record["level"].upper()
        else:
            log_record["level"] = record.levelname


config_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(message)s %(asctime)s %(name)s %(levelname)s %(lineno)s %(pathname)s %(funcName)s %(threadName)s",
            "class": "helpers.logging_config.CustomLocalJsonFormatter",
        },
        "json": {
            "format": "%(message)s %(asctime)s %(name)s %(levelname)s %(lineno)s %(pathname)s %(funcName)s %(threadName)s",
            "class": "helpers.logging_config.CustomDatadogJsonFormatter",
        },
    },
    "root": {  # root logger
        "handlers": ["default"],
        "level": "INFO",
        "propagate": True,
    },
    "handlers": {
        "default": {
            "level": "INFO",
            "formatter": "json",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",  # Default is stderr
        }
    },
    "loggers": {},
}


def get_logging_config_dict() -> dict:
    res = deepcopy(config_dict)
    if get_current_env() == Environment.local:
        res["handlers"]["default"]["formatter"] = "standard"
    return res
