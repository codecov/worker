from copy import deepcopy

from celery._state import get_current_task
from pythonjsonlogger.jsonlogger import JsonFormatter

from helpers.environment import Environment, get_current_env


class BaseLogger(JsonFormatter):
    def add_fields(self, log_record, record, message_dict) -> None:
        super(BaseLogger, self).add_fields(log_record, record, message_dict)
        task = get_current_task()
        if task and task.request:
            log_record["task_name"] = task.name
            log_record["task_id"] = task.request.id
        else:
            log_record["task_name"] = "???"
            log_record["task_id"] = "???"


class CustomLocalJsonFormatter(BaseLogger):
    def jsonify_log_record(self, log_record) -> str:
        """Returns a json string of the log record."""
        levelname = log_record.pop("levelname")
        message = log_record.pop("message")
        exc_info = log_record.pop("exc_info", "")
        content = super().jsonify_log_record(log_record)
        if exc_info:
            return f"{levelname}: {message} --- {content}\n{exc_info}"
        return f"{levelname}: {message} --- {content}"


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
        },
    },
    "loggers": {},
}


def get_logging_config_dict() -> dict:
    res = deepcopy(config_dict)
    if get_current_env() == Environment.local:
        res["handlers"]["default"]["formatter"] = "standard"
    return res
