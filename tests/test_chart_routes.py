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


    def test_chart_comments_route(self):
        fake_items = [
            {
                "tid": 1,
                "cid": 123,
                "uid": 456,
                "name": "tester",
                "content": "hello",
                "talk_type": 0,
                "is_recommend": 0,
                "talk_time": 1770000000,
                "crawl_time": "2026-04-24 00:00:00",
            }
        ]
        with patch("malody_api.routers.charts.chart_service.get_chart_comments", return_value=fake_items):
            resp = self.client.get("/charts/123/comments?limit=10&offset=0")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["data"][0]["tid"], 1)

    def test_chart_comments_exclude_recommend(self):
        with patch(
            "malody_api.routers.charts.chart_service.get_chart_comments",
            return_value=[],
        ) as mocked:
            resp = self.client.get("/charts/123/comments?include_recommend=false&limit=5&offset=2")

        self.assertEqual(resp.status_code, 200)
        mocked.assert_called_once_with(
            cid=123,
            limit=5,
            offset=2,
            include_recommend=False,
        )

    def test_chart_recommenders_route(self):
        fake_rows = [
            {
                "uid": 1661270,
                "name": "Rai1guN_",
                "recommend_records": 1,
                "first_recommend_time": "2026-04-24 00:02:27",
                "last_recommend_time": "2026-04-24 00:02:27",
            }
        ]
        with patch(
            "malody_api.routers.charts.chart_service.get_chart_recommenders",
            return_value=fake_rows,
        ):
            resp = self.client.get("/charts/155861/recommenders?limit=20&offset=0")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["data"][0]["uid"], 1661270)

    def test_chart_recommenders_route_args(self):
        with patch(
            "malody_api.routers.charts.chart_service.get_chart_recommenders",
            return_value=[],
        ) as mocked:
            resp = self.client.get("/charts/99/recommenders?limit=5&offset=3")

        self.assertEqual(resp.status_code, 200)
        mocked.assert_called_once_with(
            cid=99,
            limit=5,
            offset=3,
        )
