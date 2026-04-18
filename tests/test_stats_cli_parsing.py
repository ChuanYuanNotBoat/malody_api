import sys
from pathlib import Path
from unittest import TestCase


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.malody_stats import MalodyViz  # noqa: E402


class TestStatsCliParsing(TestCase):
    def setUp(self):
        # Bypass heavy __init__; these helpers are pure parsing logic.
        self.tool = MalodyViz.__new__(MalodyViz)

    def test_split_cli_args(self):
        args = self.tool._split_cli_args('--name "Alice Bob" --mode 0')
        self.assertEqual(args, ["--name", "Alice Bob", "--mode", "0"])

    def test_parse_cli_options(self):
        opts = self.tool._parse_cli_options(["--mode", "0", "--once"])
        self.assertEqual(opts["--mode"], "0")
        self.assertTrue(opts["--once"])

    def test_parse_cli_options_invalid_token(self):
        opts = self.tool._parse_cli_options(["mode", "0"])
        self.assertIsNone(opts)

    def test_parse_positive_int_arg(self):
        self.assertEqual(self.tool._parse_positive_int_arg("--limit", "5"), 5)
        self.assertIsNone(self.tool._parse_positive_int_arg("--limit", "0"))
        self.assertIsNone(self.tool._parse_positive_int_arg("--limit", "-2"))
        self.assertIsNone(self.tool._parse_positive_int_arg("--limit", "abc"))

