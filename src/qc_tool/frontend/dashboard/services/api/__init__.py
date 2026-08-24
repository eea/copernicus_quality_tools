"""Reusable HTTP contracts for dashboard API endpoints."""

from .json_requests import JsonRequestError
from .json_requests import read_json_object


__all__ = ("JsonRequestError", "read_json_object")
