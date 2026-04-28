import sqlite3
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.core.services.player_service import PlayerService  # noqa: E402


class TestPlayerServiceMmStats(TestCase):
    def test_get_mm_stats_excludes_zero_uid_in_top_players(self):
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE player_rankings_mm (
                mode INTEGER,
                rank INTEGER,
                uid TEXT,
                crawl_time TEXT
            );
            """
        )
        cursor.executemany(
            "INSERT INTO player_rankings_mm (mode, rank, uid, crawl_time) VALUES (?, ?, ?, ?)",
            [
                (3, 1, "0", "2026-04-01T00:00:00"),
                (3, 2, "1001", "2026-04-01T00:00:00"),
            ],
        )
        conn.commit()

        service = PlayerService()
        with patch("malody_api.core.services.player_service.get_db_connection", return_value=conn), patch.object(
            service, "_load_manual_players", return_value=[]
        ):
            data = service.get_mm_stats(mm_limit=200)

        tracked = data["tracked_players"]
        self.assertEqual(tracked["mm_top_players_count"], 1)
        self.assertEqual(tracked["union_players_count"], 1)
