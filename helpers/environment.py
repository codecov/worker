from enum import Enum
import os


class Environment(Enum):
    production = 'production'
    local = 'local'


def get_current_env():
    if os.getenv('CURRENT_ENVIRONMENT', 'production') == 'local':
        return Environment.local
    return Environment.production
