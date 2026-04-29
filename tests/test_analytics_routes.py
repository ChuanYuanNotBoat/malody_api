import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from routers.analytics import router as analytics_router  # noqa: E402


class TestAnalyticsRoutes(TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(analytics_router)
        self.client = TestClient(app)

    def test_player_compare_route(self):
        fake_data = {"players": [{"name": "alice"}], "not_found": []}
        with patch("routers.analytics.analysis_service.compare_players", return_value=fake_data):
            resp = self.client.get("/analytics/player-compare?players=alice,bob&mode=0&days=30")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(len(body["data"]["players"]), 1)

    def test_player_compare_rejects_too_many_players(self):
        players = ",".join([f"p{i}" for i in range(21)])
        resp = self.client.get(f"/analytics/player-compare?players={players}&mode=0&days=30")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("最多支持 20 个", resp.json()["detail"])

    def test_player_compare_rejects_invalid_mode(self):
        resp = self.client.get("/analytics/player-compare?players=alice&mode=10&days=30")
        self.assertEqual(resp.status_code, 422)

    def test_chart_trends_invalid_period(self):
        resp = self.client.get("/analytics/chart-trends?mode=0&period=yearly")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("period", resp.json()["detail"])

    def test_dashboard_overview_route(self):
        fake = {"database": {"file_size_bytes": 1}}
        with patch("routers.analytics.dashboard_service.get_overview", return_value=fake):
            resp = self.client.get("/analytics/dashboard-overview")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertIn("database", body["data"])

