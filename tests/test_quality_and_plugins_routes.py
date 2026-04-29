import sys
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.routers.plugins import router as plugins_router  # noqa: E402
from malody_api.routers.quality import router as quality_router  # noqa: E402


class TestQualityAndPluginsRoutes(TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(quality_router)
        app.include_router(plugins_router)
        self.client = TestClient(app)

    def test_quality_rules(self):
        resp = self.client.get("/quality/rules")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertIn("rules", body["data"])

    def test_quality_check(self):
        fake = {"score": 95, "issues": [], "severity": "low", "trend": "stable"}
        with patch("malody_api.routers.quality.quality_service.run_check", return_value=fake):
            resp = self.client.post("/quality/check?stale_hours=24", json=None)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertIn("score", body["data"])

    def test_quality_check_async_job(self):
        fake = {"score": 88, "issues": [], "severity": "medium", "trend": "stable"}
        with patch("malody_api.routers.quality.quality_service.run_check", return_value=fake):
            resp = self.client.post("/quality/check?stale_hours=24&async_mode=true", json=None)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertIn("job_id", body["data"])
        job_id = body["data"]["job_id"]

        # Poll status quickly; thread should finish almost immediately with patched runner.
        job_resp = self.client.get(f"/quality/jobs/{job_id}")
        self.assertEqual(job_resp.status_code, 200)
        job_body = job_resp.json()
        self.assertTrue(job_body["success"])
        self.assertIn("status", job_body["data"])

    def test_quality_job_not_found(self):
        resp = self.client.get("/quality/jobs/not-exist")
        self.assertEqual(resp.status_code, 404)

    def test_quality_check_invalid_stale_hours(self):
        resp = self.client.post("/quality/check?stale_hours=0", json=None)
        self.assertEqual(resp.status_code, 422)

    def test_quality_check_selected_rules_forwarded(self):
        fake = {"score": 95, "issues": [], "severity": "low", "trend": "stable"}
        with patch("malody_api.routers.quality.quality_service.run_check", return_value=fake) as mock_check:
            resp = self.client.post(
                "/quality/check?stale_hours=12",
                json=["timeliness_latest_player_crawl"],
            )
        self.assertEqual(resp.status_code, 200)
        mock_check.assert_called_once_with(
            stale_hours=12,
            selected_rules=["timeliness_latest_player_crawl"],
        )

    def test_quality_check_async_job_failed(self):
        with patch(
            "malody_api.routers.quality.quality_service.run_check",
            side_effect=RuntimeError("boom"),
        ):
            resp = self.client.post("/quality/check?stale_hours=24&async_mode=true", json=None)
        self.assertEqual(resp.status_code, 200)
        job_id = resp.json()["data"]["job_id"]

        final_status = None
        for _ in range(30):
            job_resp = self.client.get(f"/quality/jobs/{job_id}")
            self.assertEqual(job_resp.status_code, 200)
            data = job_resp.json()["data"]
            final_status = data.get("status")
            if final_status == "failed":
                self.assertEqual(data.get("error"), "boom")
                break
            time.sleep(0.01)

        self.assertEqual(final_status, "failed")

    def test_plugins_list(self):
        resp = self.client.get("/plugins")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertIn("plugins", body["data"])

    def test_plugin_not_found(self):
        resp = self.client.get("/plugins/unknown.plugin")
        self.assertEqual(resp.status_code, 404)

    def test_plugin_run(self):
        fake = {"plugin_id": "analysis.quality_snapshot", "ok": True, "result": {"score": 99}}
        with patch("malody_api.routers.plugins.plugin_service.run_plugin", return_value=fake):
            resp = self.client.post(
                "/plugins/analysis.quality_snapshot/run",
                json={"payload": {"stale_hours": 24}},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["plugin_id"], "analysis.quality_snapshot")

    def test_plugin_run_not_found(self):
        with patch(
            "malody_api.routers.plugins.plugin_service.run_plugin",
            side_effect=KeyError("plugin not found"),
        ):
            resp = self.client.post("/plugins/not-found/run", json={})
        self.assertEqual(resp.status_code, 404)

    def test_plugin_run_runtime_error_returns_api_error(self):
        with patch(
            "malody_api.routers.plugins.plugin_service.run_plugin",
            side_effect=RuntimeError("run failed"),
        ):
            resp = self.client.post("/plugins/analysis.quality_snapshot/run", json={})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"], "run failed")
