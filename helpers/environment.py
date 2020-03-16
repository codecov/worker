from enum import Enum
import os
from covreports.config import get_config


class Environment(Enum):
    production = "production"
    local = "local"


def get_current_env():
    if os.getenv("CURRENT_ENVIRONMENT", "production") == "local":
        return Environment.local
    return Environment.production


def is_enterprise():
    return bool(get_config("setup", "enterprise_license"))
