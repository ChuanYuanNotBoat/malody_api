import sys

from utils.stats_update_runner import build_update_command, run_streaming_command, split_cli_args


def install(cls, *, colorize, colors, base_dir):
    def do_update(self, arg):
        """
        更新数据（调用外部爬虫脚本）

        用法: update [--leaderboard|--player|--stb] [参数...]
        """
        tokens = split_cli_args(arg, colorize, colors.RED)
        if tokens is None:
            return

        cmd = build_update_command(
            tokens=tokens,
            base_dir=base_dir,
            python_executable=sys.executable,
            colorize=colorize,
            red=colors.RED,
            yellow=colors.YELLOW,
        )
        if cmd is None:
            return

        run_streaming_command(
            cmd=cmd,
            colorize=colorize,
            cyan=colors.CYAN,
            green=colors.GREEN,
            red=colors.RED,
        )

    setattr(cls, "do_update", do_update)
