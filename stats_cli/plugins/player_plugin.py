def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors
    def do_player(self, arg):
        """
        查看玩家信息（支持选择器筛选，参数优先）
        
        用法: player <玩家名或UID> [模式]
        参数:
        玩家名或UID - 要查询的玩家名称或UID（优先于选择器）
        模式       - 可选，模式编号，默认为当前模式（优先于选择器）
        
        示例:
        player Zani      # 查看玩家Zani在当前模式的信息（忽略选择器中的玩家筛选）
        player 123456    # 查看UID为123456的玩家
        player Zani 0    # 查看Zani在模式0的信息（忽略选择器中的模式筛选）
        """
        args = arg.split()
        if not args:
            print(colorize("错误: 请输入玩家名或UID", Colors.RED))
            return
        
        # 参数中的玩家标识符优先于选择器
        identifier = args[0]
        mode = self.current_mode
        
        # 参数中的模式优先于选择器
        if len(args) > 1:
            try:
                mode = int(args[1])
                if mode not in self.mode_names or mode == -1:
                    print(colorize("错误: 模式必须在0-9之间", Colors.RED))
                    return
            except ValueError:
                print(colorize("错误: 请输入有效的模式数字(0-9)", Colors.RED))
                return
        
        cursor = self.conn.cursor()
        
        # 判断是UID还是名称
        if identifier.isdigit():
            # UID查询
            cursor.execute(
                "SELECT player_id FROM player_identity WHERE uid = ?", 
                (identifier,)
            )
        else:
            # 名称查询
            cursor.execute(
                "SELECT player_id FROM player_aliases WHERE alias = ?",
                (identifier,)
            )
        
        result = cursor.fetchone()
        
        if not result:
            print(colorize(f"\n未找到玩家: {identifier}", Colors.YELLOW))
            return
        
        player_id = result[0]
        
        # 构建查询条件 - 使用参数中的模式，但应用选择器的其他筛选
        where_conditions = ["pr.player_id = ?", "pr.mode = ?"]
        query_params = [player_id, mode]
        
        # 应用选择器的时间筛选（如果有）
        if self.selector.filters['time_range']:
            # 获取该时间范围内的最新记录
            cursor.execute(
                """
                SELECT MAX(crawl_time) FROM player_rankings
                WHERE player_id = ? AND mode = ? AND crawl_time BETWEEN ? AND ?
                """,
                (player_id, mode,
                 self.selector.filters['time_range']['start'],
                 self.selector.filters['time_range']['end'])
            )
            latest_time = cursor.fetchone()[0]
            if latest_time:
                where_conditions.append("pr.crawl_time = ?")
                query_params.append(latest_time)
            else:
                mode_name = self.mode_names.get(mode, "未知")
                print(colorize(f"\n玩家 {identifier} 在模式 {mode} ({mode_name}) 的指定时间范围内没有数据", Colors.YELLOW))
                return
        else:
            # 无时间筛选：获取全局最新记录
            cursor.execute(
                "SELECT MAX(crawl_time) FROM player_rankings WHERE player_id = ? AND mode = ?",
                (player_id, mode)
            )
            latest_time = cursor.fetchone()[0]
            if latest_time:
                where_conditions.append("pr.crawl_time = ?")
                query_params.append(latest_time)
            else:
                mode_name = self.mode_names.get(mode, "未知")
                print(colorize(f"\n玩家 {identifier} 在模式 {mode} ({mode_name}) 中没有数据", Colors.YELLOW))
                return
        
        where_clause = " AND ".join(where_conditions)
        
        cursor.execute(
            f"""
            SELECT pr.rank, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc, pr.crawl_time
            FROM player_rankings pr
            WHERE {where_clause}
            ORDER BY pr.crawl_time DESC
            LIMIT 1
            """,
            query_params
        )
        
        player_data = cursor.fetchone()
        
        if not player_data:
            mode_name = self.mode_names.get(mode, "未知")
            print(colorize(f"\n玩家 {identifier} 在模式 {mode} ({mode_name}) 中没有数据", Colors.YELLOW))
            return
                
        rank, lv, exp, acc, combo, pc, crawl_time = player_data
            
        mode_name = self.mode_names.get(mode, "未知")
        print(colorize(f"\n玩家: {identifier} (模式 {mode} - {mode_name})", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(colorize(f"数据时间: {crawl_time}", Colors.YELLOW))
        print(get_separator())
        print(f"排名: {colorize(rank, Colors.GREEN)}")
        print(f"等级: {lv}")
        print(f"经验: {exp}")
        print(f"准确率: {colorize(f'{acc:.2f}%', Colors.GREEN)}")
        print(f"最大连击: {combo}")
        print(f"游玩次数: {pc}")
        
        cursor.execute(
            "SELECT alias FROM player_aliases WHERE player_id = ?",
            (player_id,)
        )
        aliases = [row[0] for row in cursor.fetchall()]
        
        if len(aliases) > 1:
            print(f"曾用名: {', '.join(aliases)}")
            

    setattr(cls, "do_player", db_safe_operation(do_player))

