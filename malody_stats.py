"""Compatibility entrypoint for stats CLI."""

from stats_cli.app import *  # noqa: F401,F403
from stats_cli.app import main


if __name__ == "__main__":
    raise SystemExit(main())
