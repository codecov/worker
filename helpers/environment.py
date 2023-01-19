import os
import sys
from enum import Enum
from functools import lru_cache
from pathlib import Path

from shared.config import get_config


class Environment(Enum):
    production = "production"
    local = "local"
    enterprise = "enterprise"


def get_current_env() -> Environment:
    """
        Gets the current environment of the system

    Returns:
        Environment: The current environment
    """
    return _get_cached_current_env()


def is_enterprise() -> bool:
    """Tells whether the current environment is enterprise or not

    Returns:
        bool: True if the current environment is enterprise, else False
    """
    return get_current_env() == Environment.enterprise


@lru_cache()
def _get_cached_current_env() -> Environment:
    return _calculate_current_env()


def _get_current_folder() -> str:
    return getattr(sys, "_MEIPASS", os.getcwd())


def _calculate_current_env() -> Environment:
    os.environ["CODECOV_HOME"] = _get_current_folder()
    some_dir = Path(os.getenv("CODECOV_HOME"))
    if os.path.exists(some_dir / "src/is_enterprise"):
        return Environment.enterprise
    if os.getenv("CURRENT_ENVIRONMENT", "production") == "local":
        return Environment.local
    return Environment.production


def get_external_dependencies_folder():
    return get_config(
        "services", "external_dependencies_folder", default="./external_deps"
    )
