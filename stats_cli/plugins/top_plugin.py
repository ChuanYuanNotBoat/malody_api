import copy

def install(cls, *, colorize, colors, db_safe_operation, get_separator, get_terminal_width):
    Colors = colors
    def do_top(self, arg):
        """
        查看顶级玩家排名（支持玩家和时间筛选，不支持难度筛选）
        
        用法: top [数量] [rank_type]
        参数:
        数量 - 可选，要显示的玩家数量，默认为10
        rank_type - 可选，exp 或 mm，默认为 exp
        
        示例:
        top        # 显示前10名玩家
        top 20     # 显示前20名玩家
        top mm     # 显示 MM 榜前10名玩家
        top 20 mm  # 显示 MM 榜前20名玩家
        """
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
        
        # 排行榜应忽略玩家筛选，复制选择器并清除玩家条件
        temp_selector = copy.deepcopy(self.selector)
        temp_selector.filters['players'] = []
        where_clause, params = temp_selector.build_player_sql_where("pr")
        
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
            (table,),
        )
        if not cursor.fetchone():
            print(colorize(f"missing table: {table}", Colors.YELLOW))
            return
        
        # 获取当前筛选范围内最新快照，避免混入多个时间点
        cursor.execute(
            f"SELECT MAX(pr.crawl_time) FROM {table} pr WHERE {where_clause}",
            params,
        )
        
        latest_time = cursor.fetchone()[0]
        
        if not latest_time:
            print(colorize("没有找到数据", Colors.YELLOW))
            return
        
        where_clause += " AND pr.crawl_time = ?"
        params.append(latest_time)
        
        query = f"""
        SELECT pr.mode, pr.rank, pr.name, pr.lv, pr.{value_field}, pr.acc, pr.combo, pr.pc
        FROM {table} pr
        WHERE {where_clause}
        ORDER BY pr.mode, pr.rank
        LIMIT ?
        """
        params.append(limit)
        
        cursor.execute(query, params)
        players = cursor.fetchall()
        
        if not players:
            print(colorize("没有找到符合条件的玩家", Colors.YELLOW))
            return
        
        # 显示结果
        terminal_width = get_terminal_width()
        
        if terminal_width < 100:
            col_widths = [6, 15, 6, 8, 8, 6, 8]
            header_format = "{:<6} {:<15} {:<6} {:<8} {:<8} {:<6} {:<8}"
            row_format = "{:<6} {:<15} {:<6} {:<8} {:<8.2f} {:<6} {:<8}"
        else:
            col_widths = [8, 6, 20, 6, 10, 8, 6, 8]
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
                mode, rank, name, lv, exp, acc, combo, pc = player
                if mode != current_mode:
                    mode_name = self.mode_names.get(mode, "未知")
                    print(colorize(f"\n模式 {mode} ({mode_name}):", Colors.CYAN))
                    current_mode = mode
            else:
                rank, name, lv, exp, acc, combo, pc = player[1:]  # 跳过模式列
            
            if rank == 1:
                rank_str = colorize(f"{rank}", Colors.YELLOW)
            elif rank == 2:
                rank_str = colorize(f"{rank}", Colors.WHITE)
            elif rank == 3:
                rank_str = colorize(f"{rank}", Colors.MAGENTA)
            else:
                rank_str = str(rank)
            
            if len(name) > (20 if terminal_width >= 100 else 15):
                name = name[:(17 if terminal_width >= 100 else 12)] + "..."
            
            if terminal_width >= 100:
                print(row_format.format(
                    f"{mode}", rank_str, name, lv, exp, acc, combo, pc
                ))
            else:
                print(row_format.format(
                    rank_str, name, lv, exp, acc, combo, pc
                ))
    

    setattr(cls, "do_top", db_safe_operation(do_top))

