import os
import re
import matplotlib.pyplot as plt

def install(cls, *, colorize, colors, db_safe_operation):
    Colors = colors
    def do_profile(self, arg):
        """
        查看玩家详细资料（包括头衔、成就、个人信息等）

        用法: profile <玩家名> [模式]
        参数:
        玩家名 - 要查询的玩家名称
        模式   - 可选，模式编号，默认为当前模式

        示例:
        profile Zani      # 查看Zani的详细资料
        profile Zani 0    # 查看Zani在模式0的排名信息及资料
        """
        args = arg.split()
        if not args:
            print(colorize("错误: 请输入玩家名", Colors.RED))
            return

        player_name = args[0]
        mode = self.current_mode
        if len(args) > 1:
            try:
                mode = int(args[1])
                if mode not in self.mode_names or mode == -1:
                    print(colorize("错误: 模式必须在0-9之间", Colors.RED))
                    return
            except ValueError:
                print(colorize("错误: 请输入有效的模式数字", Colors.RED))
                return

        cursor = self.conn.cursor()

        player_id = None
        uid = None

        # 根据输入获取 player_id 和 uid
        if player_name.isdigit():
            uid = player_name
            cursor.execute("SELECT player_id FROM player_identity WHERE uid = ?", (uid,))
            row = cursor.fetchone()
            if row:
                player_id = row[0]
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
            row = cursor.fetchone()
            if row:
                player_id = row[0]
                cursor.execute("SELECT uid FROM player_identity WHERE player_id = ?", (player_id,))
                uid_row = cursor.fetchone()
                if uid_row and uid_row[0]:
                    uid = uid_row[0]
            else:
                print(colorize(f"未找到玩家: {player_name}", Colors.YELLOW))
                return

        if player_id is None and uid is None:
            print(colorize(f"未找到玩家: {player_name}", Colors.YELLOW))
            return

        # 查询玩家资料（依赖 uid）
        profile = {}
        if uid:
            cursor.execute("SELECT * FROM player_profiles WHERE uid = ?", (uid,))
            row = cursor.fetchone()
            if row:
                col_names = [description[0] for description in cursor.description]
                profile = dict(zip(col_names, row))

        # 查询头衔（依赖 uid）
        titles = []
        if uid:
            cursor.execute("SELECT title FROM player_titles WHERE uid = ?", (uid,))
            titles = [r[0] for r in cursor.fetchall()]

        # 查询成就（依赖 uid）
        achievements = []
        if uid:
            cursor.execute("SELECT achievement_code FROM player_achievements WHERE uid = ?", (uid,))
            achievements = [r[0] for r in cursor.fetchall()]

        # 获取当前排名信息（依赖 player_id 和 mode）
        ranking = None
        rankings = []
        if player_id:
            if mode != -1:
                cursor.execute("""
                    SELECT rank, lv, exp, acc, combo, pc, crawl_time
                    FROM player_rankings
                    WHERE player_id = ? AND mode = ?
                    ORDER BY crawl_time DESC LIMIT 1
                """, (player_id, mode))
                ranking = cursor.fetchone()
            else:
                cursor.execute("""
                    SELECT mode, rank, lv, exp, acc, combo, pc, crawl_time
                    FROM player_rankings
                    WHERE player_id = ?
                    ORDER BY crawl_time DESC LIMIT 10
                """, (player_id,))
                rankings = cursor.fetchall()

        # 显示信息
        print(colorize(f"\n玩家详细资料: {player_name}", Colors.CYAN))
        print("-" * 40)

        if profile:
            print(colorize("基本信息:", Colors.BOLD))
            print(f"  头像: {profile.get('avatar_url', 'N/A')}")
            print(f"  加入日期: {profile.get('join_date', 'N/A')}")
            print(f"  最后游玩: {profile.get('last_play_date', 'N/A')}")
            print(f"  总游玩时长: {profile.get('total_play_time', 'N/A')}")
            print(f"  性别: {profile.get('gender', 'N/A')}")
            print(f"  年龄: {profile.get('age', 'N/A')}")
            print(f"  地区: {profile.get('location', 'N/A')}")
            print(f"  金币: {profile.get('gold', 'N/A')}")
            print(f"  收入: {profile.get('income', 'N/A')}")
            print(f"  谱面游玩时长: {profile.get('charts_played_time', 'N/A')}")
            print(f"  稳定谱面: {profile.get('stable_charts', 0)}")
            print(f"  不稳定谱面: {profile.get('unstable_charts', 0)}")
            print(f"  谱面槽位: {profile.get('chart_slots', 0)}")
            if profile.get('bio'):
                print(f"  个人简介: {profile['bio']}")
        else:
            print(colorize("无详细资料记录", Colors.YELLOW))

        if titles:
            print(colorize(f"\n头衔 ({len(titles)}):", Colors.BOLD))
            for title in titles:
                print(f"  {title}")

        if achievements:
            print(colorize(f"\n成就 ({len(achievements)}):", Colors.BOLD))
            for code in achievements[:20]:
                print(f"  {code}")
            if len(achievements) > 20:
                print(f"  ... 还有 {len(achievements)-20} 个")

        # 显示排名信息（根据 mode 决定显示方式）
        if mode != -1 and ranking:
            rank, lv, exp, acc, combo, pc, ct = ranking
            mode_name = self.mode_names.get(mode, "未知")
            print(colorize(f"\n当前排名 (模式 {mode} - {mode_name}):", Colors.BOLD))
            print(f"  排名: {rank}")
            print(f"  等级: {lv}")
            print(f"  经验: {exp}")
            print(f"  准确率: {acc:.2f}%")
            print(f"  最大连击: {combo}")
            print(f"  游玩次数: {pc}")
            print(f"  更新时间: {ct}")
        elif mode == -1 and rankings:
            print(colorize("\n各模式最新排名:", Colors.BOLD))
            for r in rankings[:5]:
                m, rank, lv, exp, acc, combo, pc, ct = r
                mode_name = self.mode_names.get(m, "未知")
                print(f"  模式 {m}({mode_name}): 排名 {rank}, 等级 {lv}, 准确率 {acc:.2f}%")

        # 只询问一次图表生成
        chart_choice = input(colorize("\n是否生成资料统计图表? (y/N): ", Colors.CYAN)).lower()
        if chart_choice == 'y':
            self._generate_profile_chart(profile, titles, achievements, player_name)
        
    def _generate_profile_chart(self, profile, titles, achievements, player_name):
        """生成玩家资料统计图表（简单示例）"""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle(f'玩家资料统计 - {player_name}', fontsize=16)

        # 左侧：头衔数量（若无头衔则显示无）
        if titles:
            # 头衔按长度分组展示（简单柱状图）
            title_len_groups = {'短(1-5)':0, '中(6-10)':0, '长(11+)':0}
            for t in titles:
                l = len(t)
                if l <= 5:
                    title_len_groups['短(1-5)'] += 1
                elif l <= 10:
                    title_len_groups['中(6-10)'] += 1
                else:
                    title_len_groups['长(11+)'] += 1
            ax1.bar(title_len_groups.keys(), title_len_groups.values(), color='lightblue')
            ax1.set_title('头衔长度分布')
            ax1.set_ylabel('数量')
        else:
            ax1.text(0.5, 0.5, '无头衔', ha='center', va='center', transform=ax1.transAxes)
            ax1.set_title('头衔')

        # 右侧：成就代码分布（按十位数分组）
        if achievements:
            # 按成就代码的十位分组（粗略分组）
            groups = {}
            for code in achievements:
                group = code // 10
                groups[group] = groups.get(group, 0) + 1
            codes = sorted(groups.keys())
            counts = [groups[k] for k in codes]
            ax2.bar([str(c) for c in codes], counts, color='lightgreen')
            ax2.set_title('成就分组分布')
            ax2.set_xlabel('成就组')
            ax2.set_ylabel('数量')
        else:
            ax2.text(0.5, 0.5, '无成就', ha='center', va='center', transform=ax2.transAxes)
            ax2.set_title('成就')

        plt.tight_layout()
        safe_name = re.sub(r'[^\w]', '_', player_name)
        filename = self.get_unique_filename(f"profile_{safe_name}.png", "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor='white')
        plt.close()
        print(colorize(f"已生成资料统计图表: {filepath}", Colors.GREEN))


    setattr(cls, "do_profile", db_safe_operation(do_profile))
    setattr(cls, "_generate_profile_chart", _generate_profile_chart)

