import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from routers.players import router as players_router  # noqa: E402


class TestPlayersRoutes(TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(players_router)
        self.client = TestClient(app)

    def test_top_players_defaults_to_exp(self):
        with patch("routers.players.player_service.get_top_players", return_value=[] ) as mocked:
            resp = self.client.get("/players/top?limit=5")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        self.assertEqual(mocked.call_args.kwargs["rank_type"], "exp")

    def test_top_players_supports_mm_rank_type(self):
        with patch("routers.players.player_service.get_top_players", return_value=[] ) as mocked:
            resp = self.client.get("/players/top?limit=5&rank_type=mm")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        self.assertEqual(mocked.call_args.kwargs["rank_type"], "mm")

    def test_player_info_supports_mm_rank_type(self):
        payload = {
            "rank": 1,
            "level": 50,
            "mm_value": 12345,
            "accuracy": 99.1,
            "combo": 9999,
            "play_count": 123,
            "mode": 0,
            "aliases": [],
            "rank_type": "mm",
        }
        with patch("routers.players.player_service.get_player_info", return_value=payload) as mocked:
            resp = self.client.get("/players/100704?rank_type=mm")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        self.assertEqual(mocked.call_args.kwargs["rank_type"], "mm")

    def test_player_info_default_exp_can_include_mm_snapshot(self):
        payload = {
            "rank": 1,
            "level": 50,
            "exp": 999999,
            "accuracy": 99.1,
            "combo": 9999,
            "play_count": 123,
            "mode": 0,
            "aliases": [],
            "rank_type": "exp",
            "mm_snapshot": {"rank": 3, "mm_value": 12000},
        }
        with patch("routers.players.player_service.get_player_info", return_value=payload) as mocked:
            resp = self.client.get("/players/100704")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertIn("mm_snapshot", body["data"])
        self.assertEqual(mocked.call_args.kwargs["rank_type"], "exp")

    def test_history_supports_mmr_metric(self):
        rows = [{"date": "2026-04-28", "mode": 0, "mmr": 12001, "mm_rank": 10}]
        with patch("routers.players.player_service.get_player_history", return_value=rows) as mocked:
            resp = self.client.get("/players/100704/history?metric=mmr&days=7")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        self.assertEqual(mocked.call_args.kwargs["metric"], "mmr")

    def test_mm_stats_endpoint_uses_requested_limit(self):
        payload = {"tracked_players": {"mm_limit": 150}}
        with patch("routers.players.player_service.get_mm_stats", return_value=payload) as mocked:
            resp = self.client.get("/players/mm/stats?mm_limit=150")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["tracked_players"]["mm_limit"], 150)
        self.assertEqual(mocked.call_args.kwargs["mm_limit"], 150)
