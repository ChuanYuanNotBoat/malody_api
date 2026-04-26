from utils.stats_export_runner import parse_export_request, run_export


def install(cls, *, colorize, colors, db_safe_operation):
    def do_export(self, arg):
        """
        导出数据文件（支持 CSV / XLSX）。

        用法:
          export <类型> [--mode 模式] [--limit 数量] [--players 玩家列表]
                        [--time-range 30d/8w/6m/1y/2025-01-01]
                        [--format csv|xlsx] [--with-summary] [--with-metadata]
        """
        request = parse_export_request(
            arg=arg,
            parse_time_range=self._parse_time_range_string,
            colorize=colorize,
            red=colors.RED,
        )
        if request is None:
            return

        run_export(
            request=request,
            conn=self.conn,
            selector=self.selector,
            output_dir=self.output_dir,
            unique_filename=self.get_unique_filename,
            colorize=colorize,
            green=colors.GREEN,
            yellow=colors.YELLOW,
            red=colors.RED,
        )

    setattr(cls, "do_export", db_safe_operation(do_export))
