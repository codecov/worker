from covreports.storage import get_appropriate_storage_service

_storage_client = None


def get_storage_client():
    return _cached_get_storage_client()


def _cached_get_storage_client():
    global _storage_client
    if _storage_client is None:
        _storage_client = get_appropriate_storage_service()
    return _storage_client
