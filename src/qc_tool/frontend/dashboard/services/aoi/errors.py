"""Stable exceptions raised at the AOI artifact boundary."""


class AoiResultUnavailable(Exception):
    """Historical or live AOI result metadata could not be read safely."""
