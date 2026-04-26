import sys
from pathlib import Path
from unittest import TestCase


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.utils.stats_export_runner import (  # noqa: E402
    ExportRequest,
    parse_export_request,
    run_export,
)
from malody_api.utils.stats_xlsx_formatter import is_change_column, is_rank_change_column  # noqa: E402


def _colorize(text: str, _color: str) -> str:
    return text


def _parse_time_range_ok(_raw: str):
    return {"start": "2026-01-01", "end": "2026-01-31"}


class TestStatsExportRunner(TestCase):
    def test_change_column_detection(self):
        self.assertTrue(is_change_column("rank_change"))
        self.assertTrue(is_change_column("exp_delta"))
        self.assertFalse(is_change_column("rank"))

    def test_rank_change_column_detection(self):
        self.assertTrue(is_rank_change_column("rank_change"))
        self.assertTrue(is_rank_change_column("排名变化"))
        self.assertFalse(is_rank_change_column("exp_change"))

    def test_parse_export_request_basic(self):
        req = parse_export_request("top --mode 0 --limit 50 --players Alice,Bob", _parse_time_range_ok, _colorize, "RED")
        self.assertIsNotNone(req)
        assert req is not None
        self.assertEqual(req.export_type, "top")
        self.assertEqual(req.mode, 0)
        self.assertEqual(req.limit, 50)
        self.assertEqual(req.players, ["Alice", "Bob"])
        self.assertEqual(req.output_format, "csv")

    def test_parse_export_request_xlsx_options(self):
        req = parse_export_request(
            "chart --format xlsx --with-summary --with-metadata",
            _parse_time_range_ok,
            _colorize,
            "RED",
        )
        self.assertIsNotNone(req)
        assert req is not None
        self.assertEqual(req.output_format, "xlsx")
        self.assertTrue(req.with_summary)
        self.assertTrue(req.with_metadata)

    def test_parse_export_request_invalid_limit(self):
        req = parse_export_request("top --limit 0", _parse_time_range_ok, _colorize, "RED")
        self.assertIsNone(req)

    def test_parse_export_request_invalid_format(self):
        req = parse_export_request("top --format pdf", _parse_time_range_ok, _colorize, "RED")
        self.assertIsNone(req)

    def test_run_export_unknown_type_returns_false(self):
        ok = run_export(
            request=ExportRequest(export_type="unknown", mode=None, limit=1, players=[], time_range=None),
            conn=None,
            selector=None,
            output_dir=".",
            unique_filename=lambda base, ext: f"{base}.{ext}",
            colorize=_colorize,
            green="GREEN",
            yellow="YELLOW",
            red="RED",
        )
        self.assertFalse(ok)

