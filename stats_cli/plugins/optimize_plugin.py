import os
import subprocess
import sys


def install(cls, *, colorize, colors, base_dir):
    def do_optimize(self, arg):
        """
        优化数据库：清理冗余记录并压缩数据库
        """
        print(colorize("正在优化数据库，请稍候...", colors.CYAN))
        script = os.path.join(base_dir, "malody_rankings.py")
        cmd = [sys.executable, script, "--optimize-db"]
        try:
            subprocess.run(cmd, check=True)
            print(colorize("数据库优化完成。", colors.GREEN))
        except subprocess.CalledProcessError as e:
            print(colorize(f"优化失败: {e}", colors.RED))

    setattr(cls, "do_optimize", do_optimize)
