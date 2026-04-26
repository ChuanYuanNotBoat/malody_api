import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.stats_cli.plugins import export_plugin, stb_creator_trends_plugin  # noqa: E402
from malody_api.utils.stats_export_runner import parse_export_request  # noqa: E402


def _colorize(text: str, _color: str) -> str:
    return text


def _db_safe_operation(func):
    def wrapper(self, *args, **kwargs):
        return func(self, *args, **kwargs)

    wrapper.__doc__ = getattr(func, "__doc__", None)
    return wrapper


class _TimeShellStub:
    def __init__(self):
        self.conn = object()
        self.selector = object()
        self.output_dir = "tmp"

    def get_unique_filename(self, base, ext):
        return f"{base}.{ext}"


class TestStatsTimeFormats(TestCase):
    @classmethod
    def setUpClass(cls):
        colors = SimpleNamespace(RED="RED", YELLOW="YELLOW", GREEN="GREEN", CYAN="CYAN")
        stb_creator_trends_plugin.install(
            _TimeShellStub,
            colorize=_colorize,
            colors=colors,
            db_safe_operation=_db_safe_operation,
        )
        export_plugin.install(
            _TimeShellStub,
            colorize=_colorize,
            colors=colors,
            db_safe_operation=_db_safe_operation,
        )

    def test_parse_time_range_string_supports_multiple_relative_formats(self):
        shell = _TimeShellStub()
        fixed_now = datetime(2026, 4, 26, 12, 0, 0)

        with patch("malody_api.stats_cli.plugins.stb_creator_trends_plugin.datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            mock_datetime.strptime.side_effect = lambda value, fmt: datetime.strptime(value, fmt)

            cases = {
                "30d": 30,
                "30D": 30,
                "30days": 30,
                "30 day": 30,
                "2w": 14,
                "2weeks": 14,
                "6m": 180,
                "6mo": 180,
                "6months": 180,
                "1y": 365,
                "1yr": 365,
                "1year": 365,
            }
            for raw, expected_days in cases.items():
                parsed = shell._parse_time_range_string(raw)
                self.assertIsNotNone(parsed, raw)
                self.assertEqual(parsed["end"], fixed_now)
                self.assertEqual((fixed_now - parsed["start"]).days, expected_days)

    def test_parse_time_range_string_supports_multiple_absolute_formats(self):
        shell = _TimeShellStub()
        fixed_now = datetime(2026, 4, 26, 12, 0, 0)

        with patch("malody_api.stats_cli.plugins.stb_creator_trends_plugin.datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            mock_datetime.strptime.side_effect = lambda value, fmt: datetime.strptime(value, fmt)

            cases = {
                "2026-01-02": datetime(2026, 1, 2),
                "2026/01/02": datetime(2026, 1, 2),
                "2026.01.02": datetime(2026, 1, 2),
                "20260102": datetime(2026, 1, 2),
                "2026-01-02 03:04": datetime(2026, 1, 2, 3, 4),
                "2026-01-02 03:04:05": datetime(2026, 1, 2, 3, 4, 5),
                "2026-01-02T03:04": datetime(2026, 1, 2, 3, 4),
                "2026-01-02T03:04:05": datetime(2026, 1, 2, 3, 4, 5),
            }
            for raw, expected_start in cases.items():
                parsed = shell._parse_time_range_string(raw)
                self.assertIsNotNone(parsed, raw)
                self.assertEqual(parsed["start"], expected_start)
                self.assertEqual(parsed["end"], fixed_now)

    def test_parse_time_range_string_rejects_invalid_input(self):
        shell = _TimeShellStub()
        self.assertIsNone(shell._parse_time_range_string(""))
        self.assertIsNone(shell._parse_time_range_string("tomorrow"))
        self.assertIsNone(shell._parse_time_range_string("2026-13-99"))

    def test_export_request_accepts_extended_time_formats(self):
        shell = _TimeShellStub()

        with patch("malody_api.stats_cli.plugins.stb_creator_trends_plugin.datetime") as mock_datetime:
            fixed_now = datetime(2026, 4, 26, 12, 0, 0)
            mock_datetime.now.return_value = fixed_now
            mock_datetime.strptime.side_effect = lambda value, fmt: datetime.strptime(value, fmt)

            req = parse_export_request(
                "history --time-range 2026/01/02T03:04:05",
                shell._parse_time_range_string,
                _colorize,
                "RED",
            )

        self.assertIsNotNone(req)
        assert req is not None
        self.assertEqual(req.time_range["start"], datetime(2026, 1, 2, 3, 4, 5))
        self.assertEqual(req.time_range["end"], fixed_now)

    def test_export_command_uses_extended_time_parser(self):
        shell = _TimeShellStub()
        with patch("malody_api.stats_cli.plugins.export_plugin.run_export") as run_mock:
            shell.do_export("history --time-range 20260102")

        run_mock.assert_called_once()
        request = run_mock.call_args.kwargs["request"]
        self.assertEqual(request.time_range["start"], datetime(2026, 1, 2))
