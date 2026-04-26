import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import pandas as pd


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.utils.stats_export_runner import (  # noqa: E402
    ExportPayload,
    ExportRequest,
    _build_export_payload,
    _build_summary_dataframe,
    run_export,
)


def _colorize(text: str, _color: str) -> str:
    return text


class _SelectorStub:
    def __init__(self):
        self.current_mode = 3
        self.filters = {}

    def __deepcopy__(self, _memo):
        copied = _SelectorStub()
        copied.current_mode = self.current_mode
        copied.filters = dict(self.filters)
        return copied

    def set_filters(self, **kwargs):
        self.filters.update(kwargs)

    def build_chart_sql_where(self, alias):
        clauses = ["1=1"]
        params = []

        modes = self.filters.get("modes")
        if modes:
            clauses.append(f"{alias}.mode = ?")
            params.append(modes[0])

        players = self.filters.get("players")
        if players:
            placeholders = ",".join("?" for _ in players)
            clauses.append(f"{alias}.stabled_by_name IN ({placeholders})")
            params.extend(players)

        time_range = self.filters.get("time_range")
        if time_range:
            clauses.append(f"{alias}.last_updated BETWEEN ? AND ?")
            params.extend([time_range["start"], time_range["end"]])

        return " AND ".join(clauses), params


class TestStatsExportRunnerPayloads(TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.selector = _SelectorStub()
        self._create_schema()
        self._seed_data()

    def tearDown(self):
        self.conn.close()

    def _create_schema(self):
        cursor = self.conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE songs (
                sid INTEGER PRIMARY KEY,
                title TEXT,
                artist TEXT
            );
            CREATE TABLE charts (
                cid INTEGER PRIMARY KEY,
                sid INTEGER,
                version TEXT,
                level REAL,
                status INTEGER,
                creator_name TEXT,
                stabled_by_name TEXT,
                heat REAL,
                donate_count INTEGER,
                play_count INTEGER,
                last_updated TEXT,
                mode INTEGER
            );
            CREATE TABLE player_rankings (
                player_id INTEGER,
                name TEXT,
                mode INTEGER,
                rank INTEGER,
                lv INTEGER,
                exp INTEGER,
                acc REAL,
                combo INTEGER,
                pc INTEGER,
                crawl_time TEXT
            );
            CREATE TABLE player_aliases (
                player_id INTEGER,
                alias TEXT
            );
            CREATE TABLE player_profiles (
                player_id INTEGER,
                uid INTEGER,
                avatar_url TEXT,
                country TEXT,
                bio TEXT,
                join_date TEXT,
                last_crawled TEXT,
                needs_update INTEGER
            );
            CREATE TABLE player_identity (
                player_id INTEGER,
                uid INTEGER,
                current_name TEXT
            );
            """
        )
        self.conn.commit()

    def _seed_data(self):
        cursor = self.conn.cursor()
        cursor.executemany(
            "INSERT INTO songs (sid, title, artist) VALUES (?, ?, ?)",
            [
                (1, "Song A", "Artist A"),
                (2, "Song B", "Artist B"),
            ],
        )
        cursor.executemany(
            """
            INSERT INTO charts
            (cid, sid, version, level, status, creator_name, stabled_by_name, heat, donate_count, play_count, last_updated, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (101, 1, "MX", 15, 2, "Creator A", "Alice", 12.5, 5, 50, "2026-01-10", 3),
                (102, 2, "HD", 10, 1, "Creator B", "Bob", 0, 0, 5, "2026-02-01", 1),
            ],
        )
        cursor.executemany(
            """
            INSERT INTO player_rankings
            (player_id, name, mode, rank, lv, exp, acc, combo, pc, crawl_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "Alice", 3, 1, 20, 2000, 99.5, 300, 10, "2026-03-01"),
                (1, "Alice", 3, 2, 19, 1800, 98.1, 250, 8, "2026-02-01"),
                (2, "Bob", 3, 2, 18, 1700, 97.0, 220, 6, "2026-03-01"),
                (3, "Carol", 1, 1, 16, 1500, 96.0, 200, 5, "2026-03-01"),
            ],
        )
        cursor.executemany(
            "INSERT INTO player_aliases (player_id, alias) VALUES (?, ?)",
            [
                (1, "Alicia"),
                (2, "Bobby"),
            ],
        )
        cursor.executemany(
            """
            INSERT INTO player_profiles
            (player_id, uid, avatar_url, country, bio, join_date, last_crawled, needs_update)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, 1001, "https://avatar/1", "CN", "bio1", "2025-01-01", "2026-03-01", 0),
                (2, 1002, "https://avatar/2", "US", "bio2", "2025-02-01", "2026-03-02", 1),
            ],
        )
        cursor.executemany(
            "INSERT INTO player_identity (player_id, uid, current_name) VALUES (?, ?, ?)",
            [
                (1, 1001, "Alice"),
                (2, 1002, "Bob"),
            ],
        )
        self.conn.commit()

    def test_build_export_payload_for_chart_export(self):
        request = ExportRequest(
            export_type="chart",
            mode=3,
            limit=10,
            players=["Alice"],
            time_range={"start": "2026-01-01", "end": "2026-01-31"},
        )

        payload = _build_export_payload(request, self.conn, self.selector, _colorize, "RED", "YELLOW")

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload.base_filename, "charts_export")
        self.assertEqual(payload.sheet_name, "charts")
        self.assertEqual(payload.metadata["row_count"], 1)
        self.assertEqual(payload.dataframe.iloc[0]["cid"], 101)

    def test_build_export_payload_for_top_export_with_player_filter(self):
        request = ExportRequest(export_type="top", mode=3, limit=10, players=["Alice"], time_range=None)

        payload = _build_export_payload(request, self.conn, self.selector, _colorize, "RED", "YELLOW")

        self.assertEqual(list(payload.dataframe["name"]), ["Alice"])
        self.assertEqual(int(payload.dataframe.iloc[0]["rank"]), 1)

    def test_build_export_payload_for_top_export_with_uid_filter(self):
        request = ExportRequest(export_type="top", mode=3, limit=10, players=["1001"], time_range=None)

        payload = _build_export_payload(request, self.conn, self.selector, _colorize, "RED", "YELLOW")

        self.assertEqual(list(payload.dataframe["name"]), ["Alice"])

    def test_build_export_payload_for_history_export_with_alias_and_time_filter(self):
        request = ExportRequest(
            export_type="history",
            mode=3,
            limit=10,
            players=["Alicia"],
            time_range={"start": "2026-01-15", "end": "2026-02-15"},
        )

        payload = _build_export_payload(request, self.conn, self.selector, _colorize, "RED", "YELLOW")

        self.assertEqual(payload.base_filename, "players_history_export")
        self.assertEqual(len(payload.dataframe), 1)
        self.assertEqual(payload.dataframe.iloc[0]["name"], "Alice")
        self.assertEqual(payload.dataframe.iloc[0]["crawl_time"], "2026-02-01")

    def test_build_export_payload_for_history_export_with_uid_filter(self):
        request = ExportRequest(export_type="history", mode=3, limit=10, players=["1001"], time_range=None)

        payload = _build_export_payload(request, self.conn, self.selector, _colorize, "RED", "YELLOW")

        self.assertEqual(set(payload.dataframe["name"]), {"Alice"})

    def test_build_export_payload_for_song_export_with_mode_filter(self):
        request = ExportRequest(export_type="song", mode=3, limit=10, players=[], time_range=None)

        payload = _build_export_payload(request, self.conn, self.selector, _colorize, "RED", "YELLOW")

        self.assertEqual(payload.base_filename, "songs_export")
        self.assertEqual(len(payload.dataframe), 1)
        self.assertEqual(int(payload.dataframe.iloc[0]["sid"]), 1)

    def test_build_export_payload_for_profile_export_with_alias_filter(self):
        request = ExportRequest(export_type="profile", mode=None, limit=10, players=["Bobby"], time_range=None)

        payload = _build_export_payload(request, self.conn, self.selector, _colorize, "RED", "YELLOW")

        self.assertEqual(payload.base_filename, "profiles_export")
        self.assertEqual(list(payload.dataframe["current_name"]), ["Bob"])
        self.assertIn("uid", payload.dataframe.columns)

    def test_build_export_payload_for_profile_export_with_uid_filter(self):
        request = ExportRequest(export_type="profile", mode=None, limit=10, players=["1001"], time_range=None)

        payload = _build_export_payload(request, self.conn, self.selector, _colorize, "RED", "YELLOW")

        self.assertEqual(list(payload.dataframe["current_name"]), ["Alice"])

    def test_build_export_payload_returns_none_when_profile_table_is_missing(self):
        cursor = self.conn.cursor()
        cursor.execute("DROP TABLE player_profiles")
        self.conn.commit()
        request = ExportRequest(export_type="profile", mode=None, limit=10, players=[], time_range=None)

        payload = _build_export_payload(request, self.conn, self.selector, _colorize, "RED", "YELLOW")

        self.assertIsNone(payload)

    def test_build_export_payload_returns_none_for_unknown_type(self):
        request = ExportRequest(export_type="mystery", mode=None, limit=10, players=[], time_range=None)

        payload = _build_export_payload(request, self.conn, self.selector, _colorize, "RED", "YELLOW")

        self.assertIsNone(payload)

    def test_build_summary_dataframe_collects_numeric_and_text_stats(self):
        df = pd.DataFrame({"rank": [1, 2, None], "name": ["Alice", "Bob", None]})

        summary_df = _build_summary_dataframe(df)

        rank_row = summary_df.loc[summary_df["column"] == "rank"].iloc[0]
        name_row = summary_df.loc[summary_df["column"] == "name"].iloc[0]
        self.assertEqual(int(rank_row["non_null"]), 2)
        self.assertEqual(float(rank_row["mean"]), 1.5)
        self.assertEqual(int(name_row["unique_count"]), 2)

    def test_run_export_writes_csv_file(self):
        payload = ExportRequest(export_type="top", mode=3, limit=10, players=[], time_range=None)

        with TemporaryDirectory() as tmpdir:
            ok = run_export(
                request=payload,
                conn=self.conn,
                selector=self.selector,
                output_dir=tmpdir,
                unique_filename=lambda base, _ext: base,
                colorize=_colorize,
                green="GREEN",
                yellow="YELLOW",
                red="RED",
            )

            self.assertTrue(ok)
            exported = Path(tmpdir) / "players_top_export.csv"
            self.assertTrue(exported.exists())
            self.assertIn("Alice", exported.read_text(encoding="utf-8-sig"))

    def test_run_export_returns_false_when_writer_fails(self):
        request = ExportRequest(export_type="top", mode=3, limit=10, players=[], time_range=None)

        with TemporaryDirectory() as tmpdir, patch.object(pd.DataFrame, "to_csv", side_effect=OSError("disk full")):
            ok = run_export(
                request=request,
                conn=self.conn,
                selector=self.selector,
                output_dir=tmpdir,
                unique_filename=lambda base, _ext: base,
                colorize=_colorize,
                green="GREEN",
                yellow="YELLOW",
                red="RED",
            )

        self.assertFalse(ok)

    def test_run_export_rejects_unsupported_format_even_with_valid_payload(self):
        request = ExportRequest(
            export_type="top",
            mode=3,
            limit=10,
            players=[],
            time_range=None,
            output_format="json",
        )

        with TemporaryDirectory() as tmpdir:
            ok = run_export(
                request=request,
                conn=self.conn,
                selector=self.selector,
                output_dir=tmpdir,
                unique_filename=lambda base, _ext: base,
                colorize=_colorize,
                green="GREEN",
                yellow="YELLOW",
                red="RED",
            )

        self.assertFalse(ok)

    def test_run_export_can_use_prebuilt_xlsx_payload_without_touching_real_database(self):
        request = ExportRequest(
            export_type="top",
            mode=3,
            limit=10,
            players=[],
            time_range=None,
            output_format="xlsx",
            with_summary=True,
            with_metadata=True,
        )
        payload = ExportPayload(
            dataframe=pd.DataFrame({"rank": [1], "name": ["Alice"]}),
            base_filename="players_top_export",
            sheet_name="top_players",
            metadata={"row_count": 1},
        )

        with TemporaryDirectory() as tmpdir, patch(
            "malody_api.utils.stats_export_runner._build_export_payload", return_value=payload
        ):
            ok = run_export(
                request=request,
                conn=self.conn,
                selector=self.selector,
                output_dir=tmpdir,
                unique_filename=lambda base, _ext: base,
                colorize=_colorize,
                green="GREEN",
                yellow="YELLOW",
                red="RED",
            )

            self.assertTrue(ok)
            self.assertTrue((Path(tmpdir) / "players_top_export.xlsx").exists())
