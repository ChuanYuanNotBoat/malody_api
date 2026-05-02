import os
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.routers.official_api import router as official_api_router  # noqa: E402


class TestOfficialAPIRoutes(TestCase):
    def setUp(self):
        os.environ.pop("MALODY_API_KEY", None)
        os.environ.pop("MALODY_API_TOKEN", None)
        app = FastAPI()
        app.include_router(official_api_router)
        self.client = TestClient(app)

    def test_guest_auth(self):
        with patch(
            "malody_api.routers.official_api.official_api_service.guest_auth",
            return_value={"code": 0, "uid": 1, "key": "k"},
        ):
            resp = self.client.get("/official-api/auth/guest")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["code"], 0)

    def test_song_info(self):
        with patch(
            "malody_api.routers.official_api.official_api_service.song_info",
            return_value={"code": 0, "sid": 123},
        ):
            resp = self.client.get("/official-api/song/123")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["sid"], 123)

