from enum import Enum
from pathlib import Path
import os
import sys
from functools import lru_cache


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
def _get_cached_current_env():
    return _calculate_current_env()


def _get_current_folder():
    return getattr(sys, "_MEIPASS", os.getcwd())


def _calculate_current_env():
    os.environ["CODECOV_HOME"] = _get_current_folder()
    some_dir = Path(os.getenv("CODECOV_HOME"))
    if os.path.exists(some_dir / "src/is_enterprise"):
        return Environment.enterprise
    if os.getenv("CURRENT_ENVIRONMENT", "production") == "local":
        return Environment.local
    return Environment.production
