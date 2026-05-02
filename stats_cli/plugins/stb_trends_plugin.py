import os
import sqlite3

import matplotlib.pyplot as plt

from selector import MCSelector


def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors

    def do_stb_trends(self, arg):
        """
        分析谱面数据趋势（支持选择器筛选）
        """
        args = arg.split()
        mode = self.current_mode
        period = "months"
        group_by = None

        i = 0
        while i < len(args):
            if args[i] in ["days", "months"]:
                period = args[i]
                i += 1
            elif args[i] == "--by" and i + 1 < len(args):
                group_by = args[i + 1].lower()
                i += 2
            elif args[i].isdigit():
                mode = int(args[i])
                i += 1
            else:
                i += 1

        cursor = self.conn.cursor()

        try:
            base_filters = self.selector.filters.copy()
            base_filters["time_range"] = None
            temp_selector = MCSelector()
            temp_selector.set_filters(**base_filters)

            where_clause, params = temp_selector.build_chart_sql_where("c")

            if not temp_selector.filters["modes"] and temp_selector.current_mode != -1:
                if where_clause != "1=1":
                    where_clause += " AND c.mode = ?"
                else:
                    where_clause = "c.mode = ?"
                params.append(mode)

            if period == "days":
                time_condition = "c.last_updated >= date('now', '-30 days')"
                group_by_time = "DATE(c.last_updated)"
                order_by = "DATE(c.last_updated)"
                period_name = "每日"
                x_label = "日期"
            else:
                time_condition = "c.last_updated >= date('now', '-1 year')"
                group_by_time = "strftime('%Y-%m', c.last_updated)"
                order_by = "strftime('%Y-%m', c.last_updated)"
                period_name = "月度"
                x_label = "月份"

            if where_clause != "1=1":
                where_clause += f" AND {time_condition}"
            else:
                where_clause = time_condition

            if group_by == "mode":
                group_col = f"{group_by_time}, c.mode"
                select_cols = f"{group_by_time} as period, c.mode, COUNT(*) as count"
                title_suffix = "按模式分组"
            elif group_by == "creator":
                group_col = f"{group_by_time}, c.creator_name"
                select_cols = f"{group_by_time} as period, c.creator_name, COUNT(*) as count"
                title_suffix = "按创作者分组"
            elif group_by == "status":
                group_col = f"{group_by_time}, c.status"
                select_cols = f"{group_by_time} as period, c.status, COUNT(*) as count"
                title_suffix = "按状态分组"
            else:
                group_col = group_by_time
                select_cols = f"{group_by_time} as period, COUNT(*) as count"
                title_suffix = ""

            query = f"""
            SELECT {select_cols}
            FROM charts c
            WHERE {where_clause}
            GROUP BY {group_col}
            ORDER BY {order_by}
            """

            cursor.execute(query, params)
            trend_data = cursor.fetchall()

            if not trend_data:
                print(colorize("没有找到趋势数据", Colors.YELLOW))
                return

            print(colorize(f"\n谱面{period_name}趋势 {title_suffix}", Colors.CYAN))
            print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
            print(get_separator())

            if group_by is None:
                dates = [row[0] for row in trend_data]
                counts = [row[1] for row in trend_data]
                total_updates = sum(counts)
                avg_updates = total_updates / len(counts) if counts else 0
                max_updates = max(counts) if counts else 0
                min_updates = min(counts) if counts else 0

                print(f"总更新谱面: {total_updates}")
                print(f"平均{period_name}更新: {avg_updates:.1f}")
                print(f"最高{period_name}更新: {max_updates}")
                print(f"最低{period_name}更新: {min_updates}")

                print(colorize(f"\n{period_name}详细数据:", Colors.BOLD))
                for date, count in trend_data[-10:]:
                    print(f"  {date}: {count} 个谱面")

                fig, ax = plt.subplots(figsize=(12, 6))
                ax.plot(dates, counts, "o-", linewidth=2, markersize=6, color="#2196F3")
                ax.fill_between(dates, counts, alpha=0.3, color="#2196F3")
                ax.axhline(y=avg_updates, color="red", linestyle="--", alpha=0.7, label=f"平均值: {avg_updates:.1f}")
                ax.set_title(f"谱面{period_name}更新趋势\n筛选条件: {self.selector.get_current_selection()}")
                ax.set_xlabel(x_label)
                ax.set_ylabel("更新谱面数量")
                ax.legend()
                ax.grid(True, alpha=0.3)
                plt.xticks(rotation=45)
                plt.tight_layout()

                base_filename = f"stb_trends_{period}_mode{mode}.png"
                filename = self.get_unique_filename(base_filename, "png")
                filepath = os.path.join(self.output_dir, filename)
                plt.savefig(filepath, dpi=150, facecolor="white")
                plt.close()
                print(colorize(f"\n已生成趋势图表: {filepath}", Colors.GREEN))
            else:
                print(colorize("\n分组趋势数据 (前20行):", Colors.BOLD))
                for row in trend_data[:20]:
                    if group_by == "mode":
                        period_value, mode_value, cnt = row
                        mode_name = self.mode_names.get(mode_value, "未知")
                        print(f"  {period_value} 模式 {mode_value}({mode_name}): {cnt}")
                    elif group_by == "creator":
                        period_value, creator, cnt = row
                        print(f"  {period_value} {creator}: {cnt}")
                    elif group_by == "status":
                        period_value, status, cnt = row
                        status_name = {0: "Alpha", 1: "Beta", 2: "Stable"}.get(status, "未知")
                        print(f"  {period_value} {status_name}: {cnt}")

                print(colorize("\n详细图表生成暂不支持分组趋势", Colors.YELLOW))

        except sqlite3.Error as e:
            print(colorize(f"数据库错误: {e}", Colors.RED))
        except Exception as e:
            print(colorize(f"操作错误: {e}", Colors.RED))

    setattr(cls, "do_stb_trends", db_safe_operation(do_stb_trends))
