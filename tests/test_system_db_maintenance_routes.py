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


class TestSystemDBMaintenanceRoutes(TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(system_router)
        self.client = TestClient(app)

    def test_db_health(self):
        with patch("malody_api.routers.system.db_maintenance_service.get_health", return_value={"ok": True}):
            resp = self.client.get("/system/db/health")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_db_maintain_requires_confirm(self):
        with patch(
            "malody_api.routers.system.db_maintenance_service.run_maintenance",
            return_value={"success": False, "error": "confirm must be true"},
        ):
            resp = self.client.post("/system/db/maintain?action=analyze&confirm=false")
        self.assertEqual(resp.status_code, 400)

    def test_db_maintain_success(self):
        fake = {"action": "analyze", "success": True}
        with patch(
            "malody_api.routers.system.db_maintenance_service.run_maintenance",
            return_value={"success": True, "result": fake},
        ):
            resp = self.client.post("/system/db/maintain?action=analyze&confirm=true")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_db_maintain_history(self):
        with patch("malody_api.routers.system.db_maintenance_service.get_history", return_value=[{"action": "vacuum"}]):
            resp = self.client.get("/system/db/maintain/history")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(len(body["data"]["history"]), 1)

