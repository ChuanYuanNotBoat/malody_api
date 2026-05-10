import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.routers.system import router as system_router  # noqa: E402


class TestSystemTaskCenterRoutes(TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(system_router)
        self.client = TestClient(app)

    def test_analysis_app_status(self):
        with patch(
            "malody_api.routers.system.analysis_app_service.discover",
            return_value={"root": "X:/mock", "entry_exists": True, "exists": True},
        ):
            resp = self.client.get("/system/analysis-app/status")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        self.assertTrue(resp.json()["data"]["entry_exists"])

    def test_launch_analysis_app(self):
        with patch(
            "malody_api.routers.system.analysis_app_service.launch",
            return_value={"ok": True, "pid": 12345},
        ):
            resp = self.client.post("/system/analysis-app/launch", json={"api_base": "http://127.0.0.1:18765"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        self.assertEqual(resp.json()["data"]["pid"], 12345)

    def test_create_system_task_unknown_action(self):
        resp = self.client.post("/system/tasks", json={"action": "unknown.action", "params": {}})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["status"], "failed")

    def test_list_system_tasks(self):
        with patch(
            "malody_api.routers.system.task_center_service.list_tasks",
            return_value=[{"task_id": "abc", "scope": "query", "status": "running"}],
        ):
            resp = self.client.get("/system/tasks?limit=10")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["count"], 1)

    def test_get_system_task_log(self):
        with patch(
            "malody_api.routers.system.task_center_service.read_task_log",
            return_value={"found": True, "task_id": "abc", "events": [{"phase": "running"}], "log_file": "tmp"},
        ):
            resp = self.client.get("/system/tasks/abc/log")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["task_id"], "abc")

