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
