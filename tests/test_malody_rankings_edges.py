import queue
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

import malody_api.malody_rankings as rankings  # noqa: E402


class TestMalodyRankingsEdges(TestCase):
    def test_source_has_no_percent_logger_without_args(self):
        source = Path(rankings.__file__).read_text(encoding="utf-8")
        bad_calls = re.findall(r'logger\.(?:info|warning|error|exception)\(\".*%.*\"\)$', source, flags=re.MULTILINE)
        self.assertEqual(
            bad_calls,
            [],
            f"Found logger calls with % placeholders but no args: {bad_calls}",
        )

    def test_load_player_config_logs_count_with_format_args(self):
        with TemporaryDirectory() as tmpdir:
            players_file = Path(tmpdir) / "players.txt"
            players_file.write_text("# comment\n1001\n\n1002\n", encoding="utf-8")

            with patch.object(rankings, "PLAYER_CONFIG_FILE", str(players_file)), patch.object(
                rankings.logger, "info"
            ) as mock_info:
                players = rankings.load_player_config()

        self.assertEqual(players, ["1001", "1002"])
        mock_info.assert_called_once()
        self.assertEqual(mock_info.call_args.args[0], "Loaded %d players from config file.")
        self.assertEqual(mock_info.call_args.args[1], 2)

    def test_add_players_to_queue_deduplicates_and_logs_count_with_format_args(self):
        test_queue: queue.Queue[str] = queue.Queue()
        test_set: set[str] = set()
        with patch.object(rankings, "player_queue", test_queue), patch.object(rankings, "_player_set", test_set), patch.object(
            rankings.logger, "info"
        ) as mock_info:
            rankings.add_players_to_queue(["1001", "1001", "1002"])

        queued = []
        while True:
            try:
                queued.append(test_queue.get_nowait())
            except queue.Empty:
                break

        self.assertEqual(queued, ["1001", "1002"])
        mock_info.assert_called_once()
        self.assertEqual(mock_info.call_args.args[0], "Added %d new players into crawl queue.")
        self.assertEqual(mock_info.call_args.args[1], 2)

    def test_parse_player_list_item_top_pc_is_prefix_agnostic(self):
        html = """
        <div class="item-top">
          <i class="label top-1"></i>
          <span class="name"><a href="/accounts/user/1001">Alice</a></span>
          <span class="lv">Lv.20-12345</span>
          <span class="acc">Acc:99.52%</span>
          <span class="combo">Combo:456</span>
          <span class="pc">游玩次数: 1,234</span>
        </div>
        <div class="item-top">
          <i class="label top-2"></i>
          <span class="name"><a href="/accounts/user/1002">Bob</a></span>
          <span class="lv">Lv.18-9999</span>
          <span class="acc">Acc:98.00%</span>
          <span class="combo">Combo:123</span>
          <span class="pc">PC=2,048</span>
        </div>
        """

        rows = rankings.parse_player_list(html)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["pc"], 1234)
        self.assertEqual(rows[1]["pc"], 2048)
