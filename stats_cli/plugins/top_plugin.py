import copy
from datetime import datetime, timedelta


def install(cls, *, colorize, colors, db_safe_operation, get_separator, get_terminal_width):
    Colors = colors

    def _parse_dt(value):
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return None

    def _query_snapshot_rows(cursor, table, value_field, where_clause, params, start_time, end_time):
        query = f"""
        WITH latest AS (
            SELECT pr.name, pr.mode, MAX(pr.crawl_time) AS max_time
            FROM {table} pr
            WHERE {where_clause}
              AND pr.crawl_time BETWEEN ? AND ?
            GROUP BY pr.name, pr.mode
        )
        SELECT pr.mode, pr.rank, pr.name, pr.lv, pr.{value_field}, pr.acc, pr.combo, pr.pc
        FROM {table} pr
        JOIN latest l
          ON l.name = pr.name
         AND l.mode = pr.mode
         AND l.max_time = pr.crawl_time
        WHERE {where_clause}
        ORDER BY pr.mode, pr.rank, pr.crawl_time DESC
        """
        query_params = params + [start_time, end_time] + params
        cursor.execute(query, query_params)
        return cursor.fetchall()

    def do_top(self, arg):
        """top [count] [exp|mm]"""
        tokens = [t for t in arg.split() if t] if arg else []
        rank_type = "exp"
        limit = None
        seen_type = False

        for tok in tokens:
            lower = tok.lower()
            if lower in ("exp", "mm"):
                if seen_type:
                    print(colorize("错误: rank_type 只能指定一次（exp/mm）", Colors.RED))
                    return
                rank_type = lower
                seen_type = True
                continue
            try:
                val = int(tok)
            except ValueError:
                print(colorize("错误: 参数仅支持 [数量] [exp|mm]", Colors.RED))
                return
            if limit is not None:
                print(colorize("错误: 数量只能指定一次", Colors.RED))
                return
            limit = val

        if limit is None:
            limit = 10
        if limit <= 0:
            print(colorize("错误: 数量必须大于0", Colors.RED))
            return
        if limit > 200:
            print(colorize("提示: 为避免刷屏，结果数量已限制为 200", Colors.YELLOW))
            limit = 200

        table = "player_rankings_mm" if rank_type == "mm" else "player_rankings"
        value_field = "mm_value" if rank_type == "mm" else "exp"
        value_label = "MM" if rank_type == "mm" else "经验"

        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1", (table,))
        if not cursor.fetchone():
            print(colorize(f"missing table: {table}", Colors.YELLOW))
            return

        temp_selector = copy.deepcopy(self.selector)
        temp_selector.filters["players"] = []
        where_clause, params = temp_selector.build_player_sql_where("pr")

        cursor.execute(f"SELECT MAX(pr.crawl_time) FROM {table} pr WHERE {where_clause}", params)
        latest_time = cursor.fetchone()[0]
        if not latest_time:
            print(colorize("没有找到数据", Colors.YELLOW))
            return

        end_time = _parse_dt(latest_time)
        if end_time is None:
            print(colorize("没有找到数据", Colors.YELLOW))
            return

        rows = []
        if temp_selector.filters.get("time_range"):
            # Keep selector-supplied lexical date/datetime format for DB comparison consistency.
            start_raw = temp_selector.filters["time_range"].get("start")
            end_raw = latest_time
            rows = _query_snapshot_rows(cursor, table, value_field, where_clause, params, start_raw, end_raw)
        else:
            min_target = min(limit, 20)
            for hours in (24, 72, 168, 720):
                candidate = _query_snapshot_rows(
                    cursor,
                    table,
                    value_field,
                    where_clause,
                    params,
                    end_time - timedelta(hours=hours),
                    end_time,
                )
                rows = candidate
                unique_rows = {(r[2], r[0]) for r in candidate}  # (name, mode)
                if len(unique_rows) >= min_target:
                    break

        dedup = []
        seen = set()
        for row in rows:
            key = (row[2], row[0])
            if key in seen:
                continue
            seen.add(key)
            dedup.append(row)
            if len(dedup) >= limit:
                break

        players = dedup
        if not players:
            print(colorize("没有找到符合条件的玩家", Colors.YELLOW))
            return

        terminal_width = get_terminal_width()
        if terminal_width < 100:
            header_format = "{:<6} {:<15} {:<6} {:<8} {:<8} {:<6} {:<8}"
            row_format = "{:<6} {:<15} {:<6} {:<8} {:<8.2f} {:<6} {:<8}"
        else:
            header_format = "{:<8} {:<6} {:<20} {:<6} {:<10} {:<8} {:<6} {:<8}"
            row_format = "{:<8} {:<6} {:<20} {:<6} {:<10} {:<8.2f} {:<6} {:<8}"

        print(colorize(f"\n顶级玩家排名 ({rank_type})", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(colorize(f"数据时间: {latest_time}", Colors.YELLOW))
        print(get_separator())

        if terminal_width >= 100:
            print(colorize(header_format.format("模式", "排名", "玩家名", "等级", value_label, "准确率", "连击", "游玩次数"), Colors.BOLD))
        else:
            print(colorize(header_format.format("排名", "玩家名", "等级", value_label, "准确率", "连击", "游玩次数"), Colors.BOLD))

        print(get_separator())

        current_mode = None
        for player in players:
            if terminal_width >= 100:
                mode, rank, name, lv, value, acc, combo, pc = player
                if mode != current_mode:
                    mode_name = self.mode_names.get(mode, "未知")
                    print(colorize(f"\n模式 {mode} ({mode_name}):", Colors.CYAN))
                    current_mode = mode
            else:
                rank, name, lv, value, acc, combo, pc = player[1:]

            if rank == 1:
                rank_str = colorize(f"{rank}", Colors.YELLOW)
            elif rank == 2:
                rank_str = colorize(f"{rank}", Colors.WHITE)
            elif rank == 3:
                rank_str = colorize(f"{rank}", Colors.MAGENTA)
            else:
                rank_str = str(rank)

            if len(name) > (20 if terminal_width >= 100 else 15):
                name = name[: (17 if terminal_width >= 100 else 12)] + "..."

            if terminal_width >= 100:
                print(row_format.format(f"{mode}", rank_str, name, lv, value, acc, combo, pc))
            else:
                print(row_format.format(rank_str, name, lv, value, acc, combo, pc))

    setattr(cls, "do_top", db_safe_operation(do_top))
