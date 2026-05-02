import sqlite3
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.routers.page_parser import router as page_parser_router  # noqa: E402


def build_test_conn():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE songs (sid INTEGER PRIMARY KEY, title TEXT, artist TEXT)")
    cur.execute(
        """
        CREATE TABLE charts (
            cid INTEGER PRIMARY KEY,
            sid INTEGER,
            mode INTEGER,
            level TEXT,
            status INTEGER,
            version TEXT,
            creator_name TEXT,
            stabled_by_name TEXT,
            heat INTEGER,
            play_count INTEGER,
            donate_count INTEGER,
            last_updated TEXT
        )
        """
    )
    cur.execute("INSERT INTO songs (sid, title, artist) VALUES (1, 'Song A', 'Artist A')")
    cur.execute(
        """
        INSERT INTO charts (cid, sid, mode, level, status, version, creator_name, stabled_by_name, heat, play_count, donate_count, last_updated)
        VALUES (100, 1, 0, '10', 2, 'v1', 'maker', 'checker', 50, 200, 3, '2026-01-01')
        """
    )
    conn.commit()
    return conn


class TestPageParserSongRoute(TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(page_parser_router)
        self.client = TestClient(app)

    def test_song_detail_route(self):
        with patch("malody_api.routers.page_parser.get_db_connection", side_effect=build_test_conn):
            resp = self.client.get("/page-parser/song/1")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["song"]["sid"], 1)
        self.assertEqual(body["data"]["stats"]["total_charts"], 1)
        self.assertEqual(len(body["data"]["charts"]), 1)

