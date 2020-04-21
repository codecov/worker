class InvalidYamlException(Exception):
    def __init__(self, error_location, original_exc=None) -> None:
        self.error_location = error_location
        self.original_exc = original_exc
