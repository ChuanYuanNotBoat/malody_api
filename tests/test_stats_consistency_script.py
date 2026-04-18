import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.scripts import check_stats_api_consistency as consistency  # noqa: E402


class TestStatsConsistencyScript(TestCase):
    def test_parse_csv_ints(self):
        self.assertEqual(consistency.parse_csv_ints(""), [])
        self.assertEqual(consistency.parse_csv_ints("0, 1,2"), [0, 1, 2])

    @patch("malody_api.scripts.check_stats_api_consistency.api_get")
    @patch("malody_api.scripts.check_stats_api_consistency.calc_top_stabilizers_baseline")
    @patch("malody_api.scripts.check_stats_api_consistency.calc_quality_baseline")
    @patch("malody_api.scripts.check_stats_api_consistency.calc_summary_baseline")
    def test_run_consistency_case(
        self,
        mock_summary,
        mock_quality,
        mock_top,
        mock_api_get,
    ):
        mock_summary.return_value = {"total_charts": 10, "unique_songs": 5, "unique_creators": 2}
        mock_quality.return_value = {
            "total_charts_checked": 10,
            "issues": {"missing_creator_name": 0, "missing_level": 0},
        }
        mock_top.return_value = [{"stabilizer_name": "Alice", "stable_count": 3}]
        mock_api_get.side_effect = [
            {"total_charts": 10, "unique_songs": 5, "unique_creators": 2},
            {"total_charts_checked": 10, "issues": {"missing_creator_name": {"count": 0}, "missing_level": {"count": 0}}},
            [{"stabilizer_name": "Alice", "stable_count": 3}],
        ]

        case = consistency.run_consistency_case(conn=None, base_url="http://localhost:8000", mode=0, limit=20)
        self.assertEqual(case["summary"]["failed_checks"], 0)
        self.assertEqual(case["mode"], 0)
        self.assertEqual(case["limit"], 20)
