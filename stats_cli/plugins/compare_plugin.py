import os
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors
    def do_compare(self, arg):
        """
        比较多个玩家的排名变化（参数优先）
        
        用法: compare <玩家1> <玩家2> [更多玩家...] [模式] [天数]
        参数:
        玩家1, 玩家2... - 要比较的玩家名称（优先于选择器）
        模式            - 可选，模式编号，默认为当前模式（优先于选择器）
        天数            - 可选，要查询的历史天数，默认为30天（优先于选择器）
        
        示例:
        compare Zani N0tYour1dol           # 比较两名玩家在当前模式最近30天的排名
        compare Zani N0tYour1dol -KIRITAN- 0 60  # 比较三名玩家在模式0最近60天的排名
        """
        args = arg.split()
        if len(args) < 2:
            print(colorize("错误: 请至少输入两个玩家名", Colors.RED))
            return
        
        players = []
        mode = self.current_mode
        days = 30
        i = 0
        
        # 解析参数中的玩家列表（优先于选择器）
        while i < len(args):
            if args[i].isdigit() and int(args[i]) in self.mode_names and int(args[i]) != -1:
                mode = int(args[i])
                i += 1
                break
            elif i > 0 and args[i].isdigit():
                days = int(args[i])
                i += 1
                break
            else:
                players.append(args[i])
                i += 1
        
        if i < len(args) and args[i].isdigit():
            days = int(args[i])
        
        if len(players) < 2:
            print(colorize("错误: 请至少输入两个玩家名", Colors.RED))
            return
        
        cursor = self.conn.cursor()
        
        # 使用参数中的天数，忽略选择器的时间筛选
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        fig, ax = plt.subplots(figsize=(12, 8))
        colors = plt.cm.Set3(np.linspace(0, 1, len(players)))
        
        for idx, player_name in enumerate(players):
            cursor.execute(
                "SELECT player_id FROM player_aliases WHERE alias = ?",
                (player_name,)
            )
            result = cursor.fetchone()
            
            if not result:
                print(colorize(f"\n未找到玩家: {player_name}", Colors.YELLOW))
                continue
            
            player_id = result[0]
            
            # 构建查询条件
            where_conditions = ["pr.player_id = ?", "pr.mode = ?", "pr.crawl_time >= ?"]
            query_params = [player_id, mode, start_date]
            
            where_clause = " AND ".join(where_conditions)
            
            cursor.execute(
                f"""
                SELECT pr.rank, pr.crawl_time
                FROM player_rankings pr
                WHERE {where_clause}
                ORDER BY pr.crawl_time
                """,
                query_params
            )
            
            history_data = cursor.fetchall()
            
            if not history_data:
                mode_name = self.mode_names.get(mode, "未知")
                print(colorize(f"\n玩家 {player_name} 在模式 {mode} ({mode_name}) 中最近 {days} 天没有数据", Colors.YELLOW))
                continue
            
            dates = [row[1] for row in history_data]
            ranks = [row[0] for row in history_data]
            
            ax.plot(dates, ranks, 'o-', linewidth=2, markersize=4, 
                color=colors[idx], label=player_name)
        
        ax.invert_yaxis()
        mode_name = self.mode_names.get(mode, "未知")
        
        # 修复字体颜色为黑色
        ax.set_title(f"Player Ranking Comparison (Mode {mode} - {mode_name})", color='black')
        ax.set_xlabel("Date", color='black')
        ax.set_ylabel("Rank", color='black')
        ax.grid(True, alpha=0.3)
        ax.legend()
        ax.tick_params(colors='black')
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        fig.autofmt_xdate()
        
        # 使用唯一文件名避免覆盖
        base_filename = f"player_comparison_mode{mode}.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, facecolor='white')
        plt.close()
        
        print(colorize(f"\n已生成玩家比较图表: {filepath}", Colors.GREEN))
    

    setattr(cls, "do_compare", db_safe_operation(do_compare))

