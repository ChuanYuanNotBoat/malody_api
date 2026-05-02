import io
import sqlite3
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.stats_cli import app as stats_app  # noqa: E402


class _DummyOps:
    @stats_app.db_safe_operation
    def sqlite_fail(self):
        raise sqlite3.Error("db down")

    @stats_app.db_safe_operation
    def generic_fail(self):
        raise RuntimeError("boom")


class TestStatsAppCore(TestCase):
    def test_db_safe_operation_catches_sqlite_error(self):
        handler = _DummyOps()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            result = handler.sqlite_fail()

        self.assertFalse(result)
        self.assertIn("db down", stdout.getvalue())

    def test_db_safe_operation_catches_generic_error(self):
        handler = _DummyOps()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            result = handler.generic_fail()

        self.assertFalse(result)
        self.assertIn("boom", stdout.getvalue())

    def test_format_change_handles_none_zero_and_reverse_rank(self):
        self.assertEqual(stats_app.format_change(None), "N/A")
        self.assertEqual(stats_app.format_change(0), "0")

        with patch("malody_api.stats_cli.app.colorize", side_effect=lambda text, _color: f"[{text}]"):
            self.assertEqual(stats_app.format_change(-3, reverse=True), "[-3]")
            self.assertEqual(stats_app.format_change(5, is_percent=True), "[+5.00%]")

    def test_execute_commands_stops_on_truthy_return_and_skips_blank_entries(self):
        shell = Mock()
        shell.onecmd.side_effect = [False, True]

        rc = stats_app._execute_commands(shell, ["   ", "mode 3", "exit", "top 5"])

        self.assertEqual(rc, 0)
        self.assertTrue(getattr(shell, "_non_interactive"))
        self.assertEqual(shell.onecmd.call_args_list[0].args[0], "mode 3")
        self.assertEqual(shell.onecmd.call_args_list[1].args[0], "exit")
        self.assertEqual(shell.onecmd.call_count, 2)

    def test_execute_commands_returns_error_on_exception(self):
        shell = Mock()
        shell.onecmd.side_effect = RuntimeError("bad command")

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = stats_app._execute_commands(shell, ["mode 3"])

        self.assertEqual(rc, 1)
        self.assertIn("bad command", stdout.getvalue())

    def test_main_returns_error_when_database_is_missing(self):
        with patch("malody_api.stats_cli.app.os.path.exists", return_value=False), patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            rc = stats_app.main([])

        self.assertEqual(rc, 1)
        self.assertIn("database file", stdout.getvalue())

    def test_main_returns_keyboard_interrupt_exit_code(self):
        with patch("malody_api.stats_cli.app.os.path.exists", return_value=True), patch(
            "malody_api.stats_cli.app.MalodyViz"
        ) as mock_viz, patch("sys.stdout", new_callable=io.StringIO) as stdout:
            mock_viz.return_value.cmdloop.side_effect = KeyboardInterrupt()
            rc = stats_app.main([])

        self.assertEqual(rc, 130)
        self.assertIn("Interrupted by user", stdout.getvalue())

    def test_main_returns_error_when_shell_initialization_fails(self):
        with patch("malody_api.stats_cli.app.os.path.exists", return_value=True), patch(
            "malody_api.stats_cli.app.MalodyViz", side_effect=RuntimeError("init failed")
        ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = stats_app.main([])

        self.assertEqual(rc, 1)
        self.assertIn("init failed", stdout.getvalue())

    def test_auto_repair_database_fixes_known_status_mismatch(self):
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE charts (
                cid INTEGER PRIMARY KEY,
                status INTEGER
            );
            INSERT INTO charts (cid, status) VALUES (139970, 0);
            """
        )
        conn.commit()

        shell = stats_app.MalodyViz.__new__(stats_app.MalodyViz)
        shell.conn = conn
        with patch("sys.stdout", new_callable=io.StringIO):
            shell.auto_repair_database()

        cursor.execute("SELECT status FROM charts WHERE cid = 139970")
        self.assertEqual(cursor.fetchone()[0], 1)
        conn.close()
