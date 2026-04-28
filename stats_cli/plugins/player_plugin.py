def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors
    def do_player(self, arg):
        """
        查看玩家信息（支持选择器筛选，参数优先）
        
        用法: player <玩家名或UID> [模式] [rank_type]
        参数:
        玩家名或UID - 要查询的玩家名称或UID（优先于选择器）
        模式       - 可选，模式编号，默认为当前模式（优先于选择器）
        rank_type  - 可选，exp 或 mm；默认不传时集成显示 EXP+MM
        
        示例:
        player Zani      # 查看玩家Zani在当前模式的信息（忽略选择器中的玩家筛选）
        player 123456    # 查看UID为123456的玩家
        player Zani 0    # 查看Zani在模式0的信息（忽略选择器中的模式筛选）
        player Zani 0 mm # 仅查看Zani在模式0的 MM 信息
        """
        args = arg.split()
        if not args:
            print(colorize("错误: 请输入玩家名或UID", Colors.RED))
            return
        
        # 参数中的玩家标识符优先于选择器
        identifier = args[0]
        mode = self.current_mode
        rank_type = "all"
        mode_set = False
        
        # 参数中的模式/rank_type 优先于选择器
        for tok in args[1:]:
            lower = tok.lower()
            if lower in ("exp", "mm"):
                rank_type = lower
                continue
            try:
                parsed_mode = int(tok)
            except ValueError:
                print(colorize("错误: 参数仅支持 [模式] [exp|mm]", Colors.RED))
                return
            if mode_set:
                print(colorize("错误: 模式只能指定一次", Colors.RED))
                return
            if parsed_mode not in self.mode_names or parsed_mode == -1:
                print(colorize("错误: 模式必须在0-9之间", Colors.RED))
                return
            mode = parsed_mode
            mode_set = True
        
        cursor = self.conn.cursor()

        def table_exists(name):
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
                (name,),
            )
            return cursor.fetchone() is not None

        has_exp_table = table_exists("player_rankings")
        has_mm_table = table_exists("player_rankings_mm")
        if not has_exp_table and not has_mm_table:
            print(colorize("当前数据库缺少 player_rankings / player_rankings_mm", Colors.YELLOW))
            return
        if rank_type == "exp" and not has_exp_table:
            print(colorize("当前数据库尚未创建 player_rankings", Colors.YELLOW))
            return
        if rank_type == "mm" and not has_mm_table:
            print(colorize("当前数据库尚未创建 MM 排行表 player_rankings_mm", Colors.YELLOW))
            return
        
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
                """
                SELECT pi.player_id
                FROM player_identity pi
                WHERE pi.current_name = ?
                UNION
                SELECT pa.player_id
                FROM player_aliases pa
                WHERE pa.alias = ?
                LIMIT 1
                """,
                (identifier, identifier)
            )
        
        result = cursor.fetchone()
        
        if not result:
            print(colorize(f"\n未找到玩家: {identifier}", Colors.YELLOW))
            return
        
        player_id = result[0]

        allowed_modes = list(self.selector.filters.get("modes") or [])

        if mode == -1:
            if rank_type == "mm":
                candidate_tables = ["player_rankings_mm", "player_rankings"]
            elif rank_type == "exp":
                candidate_tables = ["player_rankings", "player_rankings_mm"]
            else:
                candidate_tables = ["player_rankings", "player_rankings_mm"]
            for table_name in candidate_tables:
                if table_name == "player_rankings" and not has_exp_table:
                    continue
                if table_name == "player_rankings_mm" and not has_mm_table:
                    continue
                if allowed_modes:
                    placeholders = ",".join(["?"] * len(allowed_modes))
                    cursor.execute(
                        f"""
                        SELECT mode
                        FROM {table_name}
                        WHERE player_id = ? AND mode IN ({placeholders})
                        ORDER BY crawl_time DESC, mode ASC
                        LIMIT 1
                        """,
                        [player_id, *allowed_modes],
                    )
                else:
                    cursor.execute(
                        f"SELECT mode FROM {table_name} WHERE player_id = ? ORDER BY crawl_time DESC, mode ASC LIMIT 1",
                        (player_id,),
                    )
                mode_row = cursor.fetchone()
                if mode_row:
                    mode = mode_row[0]
                    break
            if mode == -1:
                print(colorize(f"\n玩家 {identifier} 没有可用数据", Colors.YELLOW))
                return

        def fetch_latest_snapshot(table_name, value_field):
            where_conditions = ["pr.player_id = ?", "pr.mode = ?"]
            query_params = [player_id, mode]
            if self.selector.filters['time_range']:
                cursor.execute(
                    f"""
                    SELECT MAX(crawl_time) FROM {table_name}
                    WHERE player_id = ? AND mode = ? AND crawl_time BETWEEN ? AND ?
                    """,
                    (
                        player_id,
                        mode,
                        self.selector.filters['time_range']['start'],
                        self.selector.filters['time_range']['end'],
                    ),
                )
                latest_time = cursor.fetchone()[0]
            else:
                cursor.execute(
                    f"SELECT MAX(crawl_time) FROM {table_name} WHERE player_id = ? AND mode = ?",
                    (player_id, mode),
                )
                latest_time = cursor.fetchone()[0]
            if not latest_time:
                return None
            where_conditions.append("pr.crawl_time = ?")
            query_params.append(latest_time)
            where_clause = " AND ".join(where_conditions)
            cursor.execute(
                f"""
                SELECT pr.rank, pr.lv, pr.{value_field}, pr.acc, pr.combo, pr.pc, pr.crawl_time
                FROM {table_name} pr
                WHERE {where_clause}
                ORDER BY pr.crawl_time DESC
                LIMIT 1
                """,
                query_params,
            )
            return cursor.fetchone()

        exp_row = fetch_latest_snapshot("player_rankings", "exp") if has_exp_table else None
        mm_row = fetch_latest_snapshot("player_rankings_mm", "mm_value") if has_mm_table else None

        if rank_type == "exp":
            if not exp_row:
                mode_name = self.mode_names.get(mode, "未知")
                print(colorize(f"\n玩家 {identifier} 在模式 {mode} ({mode_name}) 中没有 EXP 数据", Colors.YELLOW))
                return
            base_row = exp_row
        elif rank_type == "mm":
            if not mm_row:
                mode_name = self.mode_names.get(mode, "未知")
                print(colorize(f"\n玩家 {identifier} 在模式 {mode} ({mode_name}) 中没有 MM 数据", Colors.YELLOW))
                return
            base_row = mm_row
        else:
            if not exp_row and not mm_row:
                mode_name = self.mode_names.get(mode, "未知")
                print(colorize(f"\n玩家 {identifier} 在模式 {mode} ({mode_name}) 中没有数据", Colors.YELLOW))
                return
            base_row = exp_row or mm_row

        rank, lv, main_value, acc, combo, pc, crawl_time = base_row
            
        mode_name = self.mode_names.get(mode, "未知")
        print(colorize(f"\n玩家: {identifier} (模式 {mode} - {mode_name}, {rank_type})", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(colorize(f"数据时间: {crawl_time}", Colors.YELLOW))
        print(get_separator())
        print(f"排名: {colorize(rank, Colors.GREEN)}")
        print(f"等级: {lv}")
        if rank_type == "mm":
            print(f"MM: {main_value}")
        elif rank_type == "all":
            if exp_row:
                print(f"经验: {exp_row[2]}")
            else:
                print("经验: N/A")
        else:
            print(f"经验: {main_value}")
        print(f"准确率: {colorize(f'{acc:.2f}%', Colors.GREEN)}")
        print(f"最大连击: {combo}")
        print(f"游玩次数: {pc}")

        if rank_type == "all" and mm_row:
            mm_rank, _, mm_value, _, _, _, mm_time = mm_row
            print(f"MM排名: {colorize(mm_rank, Colors.GREEN)}")
            print(f"MM: {mm_value}")
            print(f"MM时间: {mm_time}")
        elif rank_type == "exp" and mm_row:
            mm_rank, _, mm_value, _, _, _, _ = mm_row
            print(f"MM(同模式最新): rank={mm_rank}, value={mm_value}")
        
        cursor.execute(
            "SELECT alias FROM player_aliases WHERE player_id = ?",
            (player_id,)
        )
        aliases = [row[0] for row in cursor.fetchall()]
        
        if len(aliases) > 1:
            print(f"曾用名: {', '.join(aliases)}")
            

    setattr(cls, "do_player", db_safe_operation(do_player))

