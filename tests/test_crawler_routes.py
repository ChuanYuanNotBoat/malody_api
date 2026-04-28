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

from malody_api.routers.crawler import router as crawler_router  # noqa: E402


class TestCrawlerRoutes(TestCase):
    def setUp(self):
        # 关闭鉴权，便于本地测试路由行为
        os.environ.pop("MALODY_API_KEY", None)
        os.environ.pop("MALODY_API_TOKEN", None)
        app = FastAPI()
        app.include_router(crawler_router)
        self.client = TestClient(app)

    def test_run_leaderboard_rejects_player_params(self):
        with patch("malody_api.routers.crawler.os.path.exists", return_value=True):
            resp = self.client.post("/crawler/run?crawler_type=leaderboard&uid=1001")
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertIn("leaderboard 不支持参数", body["detail"])

    def test_run_stb_command_mapping(self):
        with patch("malody_api.routers.crawler.os.path.exists", return_value=True), patch(
            "malody_api.routers.crawler.run_subprocess", return_value=None
        ):
            resp = self.client.post(
                "/crawler/run?crawler_type=stb&once=true&source=all&cid_crawl=true&start=10&end=20&resume=false"
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        cmd = body["data"]["command"]
        self.assertIn("--cid-crawl", cmd)
        self.assertIn("--start-cid", cmd)
        self.assertIn("--end-cid", cmd)
        self.assertIn("--no-resume", cmd)

    def test_run_leaderboard_newapi_command_mapping(self):
        with patch("malody_api.routers.crawler.os.path.exists", return_value=True), patch(
            "malody_api.routers.crawler.run_subprocess", return_value=None
        ):
            resp = self.client.post("/crawler/run?crawler_type=leaderboard&source=newapi&limit=120")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        cmd = body["data"]["command"]
        self.assertIn("--ranking-source", cmd)
        self.assertIn("newapi", cmd)
        self.assertIn("--ranking-limit", cmd)
        self.assertIn("120", cmd)

    def test_run_leaderboard_rejects_invalid_source(self):
        with patch("malody_api.routers.crawler.os.path.exists", return_value=True):
            resp = self.client.post("/crawler/run?crawler_type=leaderboard&source=all")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("leaderboard source", resp.json()["detail"])

    def test_run_leaderboard_rejects_non_positive_limit(self):
        with patch("malody_api.routers.crawler.os.path.exists", return_value=True):
            resp = self.client.post("/crawler/run?crawler_type=leaderboard&source=page&limit=0")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("limit must be > 0", resp.json()["detail"])

    def test_run_invalid_crawler_type(self):
        with patch("malody_api.routers.crawler.os.path.exists", return_value=True):
            resp = self.client.post("/crawler/run?crawler_type=unknown")
        self.assertEqual(resp.status_code, 422)

