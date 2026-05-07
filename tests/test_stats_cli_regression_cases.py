import json
import sys
from pathlib import Path
from unittest import TestCase


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.utils.stats_export_runner import parse_export_request  # noqa: E402
from malody_api.utils.stats_update_runner import build_update_command  # noqa: E402


def _colorize(text: str, _color: str) -> str:
    return text


def _parse_time_range_ok(_raw: str):
    return {"start": "2026-01-01", "end": "2026-01-31"}


class TestStatsCliRegressionCases(TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "cli_regression_cases.json"
        cls.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    def test_update_cases(self):
        for case in self.fixture["update_cases"]:
            with self.subTest(case=case["name"]):
                cmd = build_update_command(
                    tokens=case["tokens"],
                    base_dir=".",
                    python_executable="python",
                    colorize=_colorize,
                    red="RED",
                    yellow="YELLOW",
                )
                self.assertIsNotNone(cmd)
                assert cmd is not None
                normalized = [Path(cmd[1]).name, *cmd[2:]]
                self.assertEqual(normalized, case["expected_command_suffix"])

    def test_export_cases(self):
        for case in self.fixture["export_cases"]:
            with self.subTest(case=case["name"]):
                req = parse_export_request(case["arg"], _parse_time_range_ok, _colorize, "RED")
                self.assertIsNotNone(req)
                assert req is not None
                for key, expected in case["expected"].items():
                    self.assertEqual(getattr(req, key), expected)
