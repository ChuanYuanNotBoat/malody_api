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
        self.assertIn("leaderboard does not support", body["detail"])

    def test_run_stb_command_mapping(self):
        fake_task = {"task_id": "t1", "status": "running"}
        with patch("malody_api.routers.crawler.os.path.exists", return_value=True), patch(
            "malody_api.routers.crawler.crawler_task_service.create_task",
            return_value=fake_task,
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
        self.assertEqual(body["data"]["task"]["task_id"], "t1")

    def test_run_leaderboard_newapi_command_mapping(self):
        fake_task = {"task_id": "t2", "status": "running"}
        with patch("malody_api.routers.crawler.os.path.exists", return_value=True), patch(
            "malody_api.routers.crawler.crawler_task_service.create_task",
            return_value=fake_task,
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

    def test_run_player_rejects_rpm_over_limit(self):
        with patch("malody_api.routers.crawler.os.path.exists", return_value=True):
            resp = self.client.post("/crawler/run?crawler_type=player&rpm=999")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("rpm must be <=", resp.json()["detail"])

    def test_run_invalid_crawler_type(self):
        with patch("malody_api.routers.crawler.os.path.exists", return_value=True):
            resp = self.client.post("/crawler/run?crawler_type=unknown")
        self.assertEqual(resp.status_code, 422)

    def test_get_tasks_endpoint(self):
        with patch(
            "malody_api.routers.crawler.crawler_task_service.list_tasks",
            return_value=[{"task_id": "t-1", "status": "running"}],
        ):
            resp = self.client.get("/crawler/tasks")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["count"], 1)

    def test_get_task_log_not_found(self):
        with patch(
            "malody_api.routers.crawler.crawler_task_service.read_task_log",
            return_value={"found": False},
        ):
            resp = self.client.get("/crawler/tasks/missing/log")
        self.assertEqual(resp.status_code, 404)

    def test_get_task_not_found(self):
        with patch(
            "malody_api.routers.crawler.crawler_task_service.get_task",
            return_value=None,
        ):
            resp = self.client.get("/crawler/tasks/missing-task")
        self.assertEqual(resp.status_code, 404)
