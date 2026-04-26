import io
import sqlite3
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from openpyxl import load_workbook


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.stats_cli.plugins import trend_plugin  # noqa: E402


def _colorize(text: str, _color: str) -> str:
    return str(text)


def _db_safe_operation(func):
    def wrapper(self, *args, **kwargs):
        return func(self, *args, **kwargs)

    wrapper.__doc__ = getattr(func, "__doc__", None)
    return wrapper


def _separator(_width=None) -> str:
    return "----"


class _TrendShellStub:
    def __init__(self, conn, output_dir):
        self.conn = conn
        self.output_dir = output_dir
        self.current_mode = 3
        self.mode_names = {-1: "All", 3: "Catch"}
        self.selector = SimpleNamespace(get_current_selection=lambda: "Mode: 3(Catch)")
        self._non_interactive = True

    def get_unique_filename(self, base, ext):
        return f"{Path(base).stem}.{ext}"


class TestStatsTrendRenames(TestCase):
    @classmethod
    def setUpClass(cls):
        colors = SimpleNamespace(RED="RED", YELLOW="YELLOW", GREEN="GREEN", CYAN="CYAN", BLUE="BLUE", BOLD="BOLD")
        trend_plugin.install(
            _TrendShellStub,
            colorize=_colorize,
            colors=colors,
            db_safe_operation=_db_safe_operation,
            get_separator=_separator,
        )

    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.conn = sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_DECLTYPES)
        cursor = self.conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE player_rankings (
                player_id INTEGER,
                name TEXT,
                rank INTEGER,
                lv INTEGER,
                exp INTEGER,
                acc REAL,
                combo INTEGER,
                pc INTEGER,
                mode INTEGER,
                crawl_time timestamp
            );
            CREATE TABLE player_identity (
                player_id INTEGER,
                uid INTEGER,
                current_name TEXT
            );
            CREATE TABLE player_aliases (
                player_id INTEGER,
                alias TEXT
            );
            """
        )
        cursor.executemany(
            """
            INSERT INTO player_rankings
            (player_id, name, rank, lv, exp, acc, combo, pc, mode, crawl_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "OldName", 5, 10, 1000, 95.0, 100, 10, 3, datetime(2026, 1, 1, 0, 0, 0)),
                (2, "NewName", 3, 11, 1200, 96.5, 120, 12, 3, datetime(2026, 4, 1, 0, 0, 0)),
            ],
        )
        cursor.executemany(
            "INSERT INTO player_identity (player_id, uid, current_name) VALUES (?, ?, ?)",
            [
                (1, 1001, "OldName"),
                (2, 1001, "NewName"),
            ],
        )
        cursor.executemany(
            "INSERT INTO player_aliases (player_id, alias) VALUES (?, ?)",
            [
                (1, "OldName"),
                (2, "NewName"),
            ],
        )
        self.conn.commit()
        self.shell = _TrendShellStub(self.conn, self.tempdir.name)

    def tearDown(self):
        self.conn.close()
        self.tempdir.cleanup()

    def test_do_trend_treats_rename_as_same_player_not_drop_and_new(self):
        with patch("malody_api.stats_cli.plugins.trend_plugin.get_terminal_width", return_value=400), patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            self.shell.do_trend("2026-01-01")

        output = stdout.getvalue()
        self.assertIn("NewName（OldName）", output)
        self.assertIn("一直在榜: 1", output)
        self.assertIn("掉出榜: 0", output)
        self.assertIn("新上榜: 0", output)

    def test_export_trend_data_highlights_renamed_name_cell_in_blue(self):
        trend_data = [
            {
                "status": "=",
                "name": "NewName（OldName）",
                "start_rank": 5,
                "end_rank": 3,
                "rank_change": -2,
                "start_lv": 10,
                "end_lv": 11,
                "lv_change": 1,
                "start_exp": 1000,
                "end_exp": 1200,
                "exp_change": 200,
                "start_acc": 95.0,
                "end_acc": 96.5,
                "acc_change": 1.5,
                "start_combo": 100,
                "end_combo": 120,
                "combo_change": 20,
                "start_pc": 10,
                "end_pc": 12,
                "pc_change": 2,
                "renamed": True,
            }
        ]

        self.shell.export_trend_data(
            trend_data=trend_data,
            display_fields=["rank"],
            mode=3,
            start_date=datetime(2026, 1, 1),
            end_point=datetime(2026, 4, 1),
            export_format="xlsx",
        )

        workbook_bytes = Path(self.tempdir.name, "trend_mode3_20260101_20260401.xlsx").read_bytes()
        workbook = load_workbook(BytesIO(workbook_bytes), read_only=True)
        sheet = workbook["trend"]
        self.assertEqual(sheet["B2"].value, "NewName（OldName）")
        self.assertEqual(sheet["B2"].fill.start_color.rgb, "FFDDEBF7")
        del sheet
        workbook.close()
        del workbook
