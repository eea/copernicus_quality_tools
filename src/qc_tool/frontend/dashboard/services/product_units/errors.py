"""Stable exceptions raised at the product unit artifact boundary."""


class ProductUnitResultUnavailable(Exception):
    """Historical or live product unit result metadata could not be read safely."""
