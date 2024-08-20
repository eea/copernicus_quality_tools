import requests
from unittest import TestCase

FRONTEND_URL = "http://frontend:8000"

class TestAPI(TestCase):
    def test_not_authorized(self):
        resp = requests.get(f"{FRONTEND_URL}/api/delivery-list")
        assert resp.status_code == 403