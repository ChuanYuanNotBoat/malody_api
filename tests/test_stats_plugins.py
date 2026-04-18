import sys
from pathlib import Path
from unittest import TestCase


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.malody_stats import MalodyViz  # noqa: E402


class TestStatsPlugins(TestCase):
    def test_plugin_overrides_are_installed(self):
        self.assertEqual(MalodyViz.do_update.__module__, "stats_cli.plugins.update_plugin")
        self.assertEqual(MalodyViz.do_crawl_status.__module__, "stats_cli.plugins.crawl_status_plugin")
        self.assertEqual(MalodyViz.do_mode.__module__, "stats_cli.plugins.utility_plugin")
        self.assertEqual(MalodyViz.do_exit.__module__, "stats_cli.plugins.utility_plugin")
        self.assertEqual(MalodyViz.do_alias.__module__, "stats_cli.plugins.alias_plugin")
        self.assertEqual(MalodyViz.do_help.__module__, "stats_cli.plugins.help_plugin")
        self.assertEqual(MalodyViz.do_select.__module__, "stats_cli.plugins.select_plugin")
        self.assertEqual(MalodyViz.do_repair.__module__, "stats_cli.plugins.repair_plugin")
        self.assertEqual(MalodyViz.do_top.__module__, "stats_cli.plugins.top_plugin")
        self.assertEqual(MalodyViz.do_player.__module__, "stats_cli.plugins.player_plugin")
        self.assertEqual(MalodyViz.do_profile.__module__, "stats_cli.plugins.profile_plugin")
        self.assertEqual(MalodyViz.do_history.__module__, "stats_cli.plugins.history_plugin")
        self.assertEqual(MalodyViz.do_compare.__module__, "stats_cli.plugins.compare_plugin")
        self.assertEqual(MalodyViz.do_top_chart.__module__, "stats_cli.plugins.top_chart_plugin")
        self.assertEqual(MalodyViz.do_trend.__module__, "stats_cli.plugins.trend_plugin")
        self.assertEqual(MalodyViz.do_search.__module__, "stats_cli.plugins.search_plugin")
        self.assertEqual(MalodyViz.do_stb_stats.__module__, "stats_cli.plugins.stb_stats_plugin")
