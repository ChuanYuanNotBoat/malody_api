import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.routers.charts import router as charts_router  # noqa: E402


class TestChartRoutes(TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(charts_router)
        self.client = TestClient(app)

    def test_summary_route(self):
        with patch("malody_api.routers.charts.chart_service.get_chart_summary", return_value={"total_charts": 1}):
            resp = self.client.get("/charts/summary")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["total_charts"], 1)

    def test_quality_route(self):
        with patch("malody_api.routers.charts.chart_service.get_chart_quality", return_value={"missing_creator_ratio": 0.0}):
            resp = self.client.get("/charts/quality")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertIn("missing_creator_ratio", body["data"])

    def test_stabilizers_top_route(self):
        with patch(
            "malody_api.routers.charts.chart_service.get_top_stabilizers",
            return_value=[{"player_name": "alice", "stable_count": 10}],
        ):
            resp = self.client.get("/charts/stabilizers/top?mode=0&limit=20")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(len(body["data"]), 1)

    def test_creator_details_invalid_status(self):
        resp = self.client.get("/charts/creators/alice/details?status=3")
        self.assertEqual(resp.status_code, 422)

    def test_creator_trends_invalid_mode(self):
        resp = self.client.get("/charts/creators/alice/trends?mode=10")
        self.assertEqual(resp.status_code, 422)

    def test_summary_invalid_detail_level(self):
        resp = self.client.get("/charts/summary?detail_level=full")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("detail_level", resp.json()["detail"])

    def test_quality_invalid_time_range(self):
        resp = self.client.get("/charts/quality?time_range=bad-format")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("time_range", resp.json()["detail"])

    def test_creator_trends_since_last_conflict(self):
        resp = self.client.get("/charts/creators/alice/trends?since=2026-01-01&last=30d")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("不能同时使用", resp.json()["detail"])

