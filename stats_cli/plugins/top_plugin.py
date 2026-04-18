import copy

def install(cls, *, colorize, colors, db_safe_operation, get_separator, get_terminal_width):
    Colors = colors
    def do_top(self, arg):
        """
        查看顶级玩家排名（支持玩家和时间筛选，不支持难度筛选）
        
        用法: top [数量]
        参数:
        数量 - 可选，要显示的玩家数量，默认为10
        
        示例:
        top        # 显示前10名玩家
        top 20     # 显示前20名玩家
        """
        try:
            limit = int(arg) if arg else 10
            if limit <= 0:
                print(colorize("错误: 数量必须大于0", Colors.RED))
                return
        except ValueError:
            print(colorize("错误: 请输入有效的数字", Colors.RED))
            return
        
        # 排行榜应忽略玩家筛选，复制选择器并清除玩家条件
        temp_selector = copy.deepcopy(self.selector)
        temp_selector.filters['players'] = []
        where_clause, params = temp_selector.build_player_sql_where("pr")
        
        cursor = self.conn.cursor()
        
        # 获取最新爬取时间
        if temp_selector.filters['modes']:
            mode_condition = "pr.mode IN ({})".format(','.join(['?']*len(temp_selector.filters['modes'])))
            cursor.execute(
                f"SELECT MAX(crawl_time) FROM player_rankings pr WHERE {mode_condition}",
                temp_selector.filters['modes']
            )
        elif temp_selector.current_mode != -1:
            cursor.execute(
                "SELECT MAX(crawl_time) FROM player_rankings WHERE mode = ?",
                (temp_selector.current_mode,)
            )
        else:
            cursor.execute("SELECT MAX(crawl_time) FROM player_rankings")
        
        latest_time = cursor.fetchone()[0]
        
        if not latest_time:
            print(colorize("没有找到数据", Colors.YELLOW))
            return
        
        # 添加时间条件（如果没有设置时间筛选）
        if not temp_selector.filters['time_range']:
            if "crawl_time" not in where_clause:
                where_clause += " AND pr.crawl_time = ?"
                params.append(latest_time)
        
        query = f"""
        SELECT pr.mode, pr.rank, pr.name, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc
        FROM player_rankings pr
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
        
        print(colorize(f"\n顶级玩家排名", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        if not temp_selector.filters['time_range']:
            print(colorize(f"数据时间: {latest_time}", Colors.YELLOW))
        print(get_separator())
        
        if terminal_width >= 100:
            print(colorize(header_format.format("模式", "排名", "玩家名", "等级", "经验", "准确率", "连击", "游玩次数"), Colors.BOLD))
        else:
            print(colorize(header_format.format("排名", "玩家名", "等级", "经验", "准确率", "连击", "游玩次数"), Colors.BOLD))
        
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

