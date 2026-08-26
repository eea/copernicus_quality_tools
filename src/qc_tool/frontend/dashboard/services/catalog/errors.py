"""Safe product-catalog failures surfaced by commands and services."""


class CatalogError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

