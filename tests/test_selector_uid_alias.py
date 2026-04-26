import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from unittest import TestCase


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.selector import MCSelector  # noqa: E402


class TestSelectorUidAlias(TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_DECLTYPES)
        cursor = self.conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE player_identity (
                player_id INTEGER,
                uid INTEGER,
                current_name TEXT
            );
            CREATE TABLE player_aliases (
                player_id INTEGER,
                alias TEXT
            );
            CREATE TABLE player_rankings (
                player_id INTEGER,
                mode INTEGER,
                name TEXT,
                crawl_time timestamp
            );
            """
        )
        cursor.execute("INSERT INTO player_identity (player_id, uid, current_name) VALUES (1, 1001, 'Alice')")
        cursor.executemany(
            "INSERT INTO player_aliases (player_id, alias) VALUES (1, ?)",
            [("Alicia",), ("OldAlice",)],
        )
        cursor.executemany(
            "INSERT INTO player_rankings (player_id, mode, name, crawl_time) VALUES (?, ?, ?, ?)",
            [
                (1, 3, "Alice", datetime(2026, 4, 1)),
                (1, 3, "OldAlice", datetime(2026, 3, 1)),
            ],
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_uid_filter_matches_rows_even_without_uid_column(self):
        selector = MCSelector()
        selector.set_filters(players=["1001"])
        where, params = selector.build_player_sql_where("pr")

        cursor = self.conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM player_rankings pr WHERE {where}", params)
        count = cursor.fetchone()[0]

        self.assertEqual(count, 2)

    def test_alias_filter_matches_current_and_historical_names_via_player_id(self):
        selector = MCSelector()
        selector.set_filters(players=["Alicia"])
        where, params = selector.build_player_sql_where("pr")

        cursor = self.conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM player_rankings pr WHERE {where}", params)
        count = cursor.fetchone()[0]

        self.assertEqual(count, 2)
