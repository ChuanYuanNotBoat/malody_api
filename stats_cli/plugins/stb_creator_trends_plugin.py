import copy
import os
import re
from datetime import datetime, timedelta

import matplotlib.pyplot as plt


def install(cls, *, colorize, colors, db_safe_operation):
    Colors = colors

    def do_stb_creator_trends(self, arg):
        """
        分析特定创作者的谱面更新趋势
        """
        args = arg.split()
        if not args:
            print(colorize("错误: 请输入创作者名", Colors.RED))
            return

        creator = args[0]
        period = "months"
        time_range = None

        i = 1
        while i < len(args):
            if args[i] in ["days", "months"]:
                period = args[i]
                i += 1
            elif args[i] == "--since":
                if i + 1 >= len(args):
                    print(colorize("错误: --since 需要指定日期 (YYYY-MM-DD)", Colors.RED))
                    return
                try:
                    start_date = datetime.strptime(args[i + 1], "%Y-%m-%d")
                    time_range = {"start": start_date, "end": datetime.now()}
                    i += 2
                except ValueError:
                    print(colorize("错误: 日期格式应为 YYYY-MM-DD", Colors.RED))
                    return
            elif args[i] == "--last":
                if i + 1 >= len(args):
                    print(colorize("错误: --last 需要指定时间范围 (如 30d, 6m)", Colors.RED))
                    return
                time_str = args[i + 1]
                parsed = self._parse_time_range_string(time_str)
                if parsed:
                    time_range = parsed
                    i += 2
                else:
                    print(colorize(f"错误: 无法解析时间范围 '{time_str}'", Colors.RED))
                    return
            else:
                i += 1

        selector = copy.deepcopy(self.selector)
        selector.set_filters(players=[creator])
        where_clause, params = selector.build_chart_sql_where("c")

        if time_range:
            start = time_range["start"]
            end = time_range["end"]
            time_condition = "c.last_updated BETWEEN ? AND ?"
            params.extend([start, end])
            if where_clause != "1=1":
                where_clause += f" AND {time_condition}"
            else:
                where_clause = time_condition

        if period == "days":
            group_by = "DATE(c.last_updated)"
            order_by = "DATE(c.last_updated)"
            x_label = "日期"
        else:
            group_by = "strftime('%Y-%m', c.last_updated)"
            order_by = "strftime('%Y-%m', c.last_updated)"
            x_label = "月份"

        query = f"""
        SELECT {group_by}, COUNT(*)
        FROM charts c
        WHERE {where_clause}
        GROUP BY {group_by}
        ORDER BY {order_by}
        """
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        trend_data = cursor.fetchall()

        if not trend_data:
            print(colorize("没有找到趋势数据", Colors.YELLOW))
            return

        dates = [row[0] for row in trend_data]
        counts = [row[1] for row in trend_data]
        total = sum(counts)
        avg = total / len(counts)

        print(colorize(f"\n创作者 {creator} 的谱面更新趋势 ({period})", Colors.CYAN))
        if time_range:
            print(
                colorize(
                    f"时间范围: {time_range['start'].strftime('%Y-%m-%d')} 至 {time_range['end'].strftime('%Y-%m-%d')}",
                    Colors.YELLOW,
                )
            )
        else:
            print(colorize("时间范围: 全部时间", Colors.YELLOW))
        print(f"总更新谱面: {total}, 平均{period}更新: {avg:.1f}")

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(dates, counts, "o-", linewidth=2, markersize=6, color="#2196F3")
        ax.fill_between(dates, counts, alpha=0.3, color="#2196F3")
        ax.axhline(y=avg, color="red", linestyle="--", alpha=0.7, label=f"平均 {avg:.1f}")
        ax.set_title(f"创作者 {creator} 谱面更新趋势")
        ax.set_xlabel(x_label)
        ax.set_ylabel("更新谱面数量")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()

        safe_creator = re.sub(r"[^\w]", "_", creator)
        filename = self.get_unique_filename(f"creator_trends_{safe_creator}_{period}.png", "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor="white")
        plt.close()
        print(colorize(f"已生成趋势图表: {filepath}", Colors.GREEN))

    def _parse_time_range_string(self, time_str):
        now = datetime.now()
        try:
            if time_str.endswith("d"):
                days = int(time_str[:-1])
                return {"start": now - timedelta(days=days), "end": now}
            if time_str.endswith("w"):
                weeks = int(time_str[:-1])
                return {"start": now - timedelta(weeks=weeks), "end": now}
            if time_str.endswith("m"):
                months = int(time_str[:-1])
                return {"start": now - timedelta(days=months * 30), "end": now}
            if time_str.endswith("y"):
                years = int(time_str[:-1])
                return {"start": now - timedelta(days=years * 365), "end": now}

            start = datetime.strptime(time_str, "%Y-%m-%d")
            return {"start": start, "end": now}
        except Exception:
            return None

    setattr(cls, "do_stb_creator_trends", db_safe_operation(do_stb_creator_trends))
    setattr(cls, "_parse_time_range_string", _parse_time_range_string)
