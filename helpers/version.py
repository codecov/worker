import os


def get_current_version():
    return os.getenv("RELEASE_VERSION", "NO_VERSION")
