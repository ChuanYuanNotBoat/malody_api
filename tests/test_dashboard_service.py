import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.core.models import ChartStats  # noqa: E402
from malody_api.core.services.dashboard_service import DashboardService  # noqa: E402


class TestDashboardService(TestCase):
    def test_get_overview_accepts_chartstats_model(self):
        svc = DashboardService()
        with patch.object(svc.player_service, "get_mm_stats", return_value={"freshness": {}, "tracked_players": {}}), patch.object(
            svc.chart_service,
            "get_chart_stats",
            return_value=ChartStats(
                total_charts=12,
                unique_songs=10,
                unique_creators=3,
                status_distribution={"0": 7, "1": 3, "2": 2},
                level_distribution={},
                heat_stats={},
            ),
        ), patch(
            "malody_api.core.services.dashboard_service.db_maintenance_service.get_health",
            return_value={"db_path": "x", "file_size_bytes": 1, "fragmentation_ratio": 0, "quick_check": "ok"},
        ), patch(
            "malody_api.core.services.dashboard_service.crawler_task_service.summarize",
            return_value={"total": 0, "running": 0, "failed": 0, "finished": 0, "latest": []},
        ):
            out = svc.get_overview()

        self.assertEqual(out["charts"]["total_charts"], 12)
        self.assertEqual(out["charts"]["unique_songs"], 10)
        self.assertEqual(out["charts"]["unique_creators"], 3)

