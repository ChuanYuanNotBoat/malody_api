import os
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta

def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors
    def do_history(self, arg):
        """
        查看玩家历史排名并生成图表（参数优先）
        
        用法: history <玩家名> [模式] [天数]
        参数:
        玩家名 - 要查询的玩家名称（优先于选择器）
        模式   - 可选，模式编号，默认为当前模式（优先于选择器）
        天数   - 可选，要查询的历史天数，默认为30天（优先于选择器）
        
        示例:
        history Zani        # 查看Zani在当前模式最近30天的历史（忽略选择器）
        history Zani 0 60   # 查看Zani在模式0最近60天的历史（忽略选择器）
        """
        args = arg.split()
        if not args:
            print(colorize("错误: 请输入玩家名", Colors.RED))
            return
        
        # 参数中的玩家名优先于选择器
        player_name = args[0]
        mode = self.current_mode
        days = 30
        
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
        
        # 参数中的天数优先于选择器
        if len(args) > 2:
            try:
                days = int(args[2])
                if days <= 0:
                    print(colorize("错误: 天数必须大于0", Colors.RED))
                    return
            except ValueError:
                print(colorize("错误: 请输入有效的天数", Colors.RED))
                return
        
        cursor = self.conn.cursor()
        
        if player_name.isdigit():
            cursor.execute(
                "SELECT player_id FROM player_identity WHERE uid = ?",
                (player_name,),
            )
        else:
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
                (player_name, player_name),
            )
        result = cursor.fetchone()
        
        if not result:
            print(colorize(f"\n未找到玩家: {player_name}", Colors.YELLOW))
            return
        
        player_id = result[0]
        
        # 使用参数中的天数，忽略选择器的时间筛选
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
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
            return
        
        dates = [row[1] for row in history_data]
        ranks = [row[0] for row in history_data]
        
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(dates, ranks, 'o-', linewidth=2, markersize=4)
        ax.invert_yaxis()
        mode_name = self.mode_names.get(mode, "未知")
        
        # 修复字体颜色为黑色
        ax.set_title(f"Player {player_name} Ranking History (Mode {mode} - {mode_name})", color='black')
        ax.set_xlabel("Date", color='black')
        ax.set_ylabel("Rank", color='black')
        ax.grid(True, alpha=0.3)
        
        # 设置刻度颜色
        ax.tick_params(colors='black')
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        fig.autofmt_xdate()
        
        # 使用唯一文件名避免覆盖
        base_filename = f"player_history_{player_name}_mode{mode}.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, facecolor='white')  # 设置背景为白色
        plt.close()
        
        print(colorize(f"\n已生成历史排名图表: {filepath}", Colors.GREEN))
        
        print(colorize(f"\n{player_name} 最近排名变化:", Colors.CYAN))
        print(get_separator())
        for i, (rank, date) in enumerate(history_data[-10:] if len(history_data) > 10 else history_data):
            print(f"{date.strftime('%Y-%m-%d')}: #{rank}")

    setattr(cls, "do_history", db_safe_operation(do_history))
