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

        def table_exists(table_name):
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
                (table_name,),
            )
            return cursor.fetchone() is not None

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

        # 获取当前排名信息（依赖 player_id）
        ranking = None
        rankings = []
        if player_id:
            exp_by_mode = {}
            mm_by_mode = {}

            if table_exists("player_rankings"):
                cursor.execute(
                    """
                    SELECT e.mode, e.rank, e.lv, e.exp, e.acc, e.combo, e.pc, e.crawl_time
                    FROM player_rankings e
                    JOIN (
                        SELECT mode, MAX(crawl_time) AS max_ct
                        FROM player_rankings
                        WHERE player_id = ?
                        GROUP BY mode
                    ) t ON t.mode = e.mode AND t.max_ct = e.crawl_time
                    WHERE e.player_id = ?
                    ORDER BY e.mode
                    """,
                    (player_id, player_id),
                )
                for row in cursor.fetchall():
                    exp_by_mode[row[0]] = {
                        "rank": row[1],
                        "lv": row[2],
                        "exp": row[3],
                        "acc": row[4],
                        "combo": row[5],
                        "pc": row[6],
                        "crawl_time": row[7],
                    }

            if table_exists("player_rankings_mm"):
                cursor.execute(
                    """
                    SELECT m.mode, m.rank, m.mm_value, m.crawl_time
                    FROM player_rankings_mm m
                    JOIN (
                        SELECT mode, MAX(crawl_time) AS max_ct
                        FROM player_rankings_mm
                        WHERE player_id = ?
                        GROUP BY mode
                    ) t ON t.mode = m.mode AND t.max_ct = m.crawl_time
                    WHERE m.player_id = ?
                    ORDER BY m.mode
                    """,
                    (player_id, player_id),
                )
                for row in cursor.fetchall():
                    mm_by_mode[row[0]] = {
                        "mm_rank": row[1],
                        "mm_value": row[2],
                        "mm_crawl_time": row[3],
                        "mmr": None,
                    }

            # 回退：非 MM 榜玩家从 player_mmr_daily 补齐 mm_rank/mmr（按 mode 最新 day）
            if uid and table_exists("player_mmr_daily"):
                cursor.execute(
                    """
                    SELECT d.mode, d.mm_rank, d.mmr, d.sample_time
                    FROM player_mmr_daily d
                    JOIN (
                        SELECT mode, MAX(day) AS max_day
                        FROM player_mmr_daily
                        WHERE uid = ?
                        GROUP BY mode
                    ) t ON t.mode = d.mode AND t.max_day = d.day
                    JOIN (
                        SELECT mode, day, MAX(sample_time) AS max_sample_time
                        FROM player_mmr_daily
                        WHERE uid = ?
                        GROUP BY mode, day
                    ) s ON s.mode = d.mode
                       AND s.day = d.day
                       AND s.max_sample_time = d.sample_time
                    WHERE d.uid = ?
                    ORDER BY d.mode
                    """,
                    (str(uid), str(uid), str(uid)),
                )
                for row in cursor.fetchall():
                    mode_key = row[0]
                    bucket = mm_by_mode.get(mode_key, {})
                    if bucket.get("mm_rank") is None:
                        bucket["mm_rank"] = row[1]
                    # 对非 MM 榜玩家，MM 值默认使用 MMR 值展示
                    if bucket.get("mm_value") is None:
                        bucket["mm_value"] = row[2]
                    bucket["mmr"] = row[2]
                    if bucket.get("mm_crawl_time") is None:
                        bucket["mm_crawl_time"] = row[3]
                    mm_by_mode[mode_key] = bucket

            all_modes = sorted(set(exp_by_mode.keys()) | set(mm_by_mode.keys()))
            merged = []
            for m in all_modes:
                exp_row = exp_by_mode.get(m, {})
                mm_row = mm_by_mode.get(m, {})
                merged.append(
                    {
                        "mode": m,
                        "rank": exp_row.get("rank"),
                        "lv": exp_row.get("lv"),
                        "exp": exp_row.get("exp"),
                        "acc": exp_row.get("acc"),
                        "combo": exp_row.get("combo"),
                        "pc": exp_row.get("pc"),
                        "crawl_time": exp_row.get("crawl_time"),
                        "mm_rank": mm_row.get("mm_rank"),
                        "mm_value": mm_row.get("mm_value"),
                        "mmr": mm_row.get("mmr"),
                        "mm_crawl_time": mm_row.get("mm_crawl_time"),
                    }
                )

            if mode != -1:
                ranking = next((r for r in merged if r["mode"] == mode), None)
            else:
                rankings = sorted(
                    merged,
                    key=lambda x: (x["exp"] is None, -(x["exp"] if x["exp"] is not None else -1)),
                )

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
            rank = ranking.get("rank")
            lv = ranking.get("lv")
            exp = ranking.get("exp")
            acc = ranking.get("acc")
            combo = ranking.get("combo")
            pc = ranking.get("pc")
            ct = ranking.get("crawl_time")
            mm_rank = ranking.get("mm_rank")
            mm_value = ranking.get("mm_value")
            mmr = ranking.get("mmr")
            mm_ct = ranking.get("mm_crawl_time")
            mode_name = self.mode_names.get(mode, "未知")
            print(colorize(f"\n当前排名 (模式 {mode} - {mode_name}):", Colors.BOLD))
            print(f"  EXP排名: {rank if rank is not None else 'N/A'}")
            print(f"  等级: {lv if lv is not None else 'N/A'}")
            print(f"  EXP: {exp if exp is not None else 'N/A'}")
            acc_text = f"{acc:.2f}%" if isinstance(acc, (float, int)) else "N/A"
            print(f"  准确率: {acc_text}")
            print(f"  最大连击: {combo if combo is not None else 'N/A'}")
            print(f"  游玩次数: {pc if pc is not None else 'N/A'}")
            print(f"  EXP更新时间: {ct if ct is not None else 'N/A'}")
            print(f"  MM排名: {mm_rank if mm_rank is not None else 'N/A'}")
            print(f"  MM: {mm_value if mm_value is not None else 'N/A'}")
            print(f"  MMR: {mmr if mmr is not None else 'N/A'}")
            if mm_ct is not None:
                print(f"  MM更新时间: {mm_ct}")
        elif mode == -1 and rankings:
            print(colorize("\n各模式最新排名:", Colors.BOLD))
            for row in rankings:
                m = row["mode"]
                mode_name = self.mode_names.get(m, "未知")
                rank = row["rank"]
                lv = row["lv"]
                exp = row["exp"]
                acc = row["acc"]
                mm_rank = row["mm_rank"]
                mm_value = row["mm_value"]
                mmr = row["mmr"]
                acc_text = f"{acc:.2f}%" if isinstance(acc, (float, int)) else "N/A"
                print(
                    f"  模式 {m}({mode_name}): "
                    f"EXP排名 {rank if rank is not None else 'N/A'}, "
                    f"EXP {exp if exp is not None else 'N/A'}, "
                    f"MM排名 {mm_rank if mm_rank is not None else 'N/A'}, "
                    f"MM {mm_value if mm_value is not None else 'N/A'}, "
                    f"MMR {mmr if mmr is not None else 'N/A'}, "
                    f"等级 {lv if lv is not None else 'N/A'}, "
                    f"准确率 {acc_text}"
                )

        # 只询问一次图表生成
        chart_choice = input(colorize("\n是否生成资料统计图表? (y/N): ", Colors.CYAN)).lower()
        if chart_choice == 'y':
            self._generate_profile_chart(profile, titles, achievements, player_name, ranking, rankings, mode)

    def _generate_profile_chart(self, profile, titles, achievements, player_name, ranking, rankings, mode):
        """Generate per-mode profile charts."""
        rows = []
        if mode == -1:
            rows = list(rankings or [])
        elif ranking:
            rows = [dict(ranking)]
        if not rows:
            print(colorize("[profile] Skip chart: no ranking data available.", Colors.YELLOW))
            return

        mode_labels = [str(r.get("mode")) for r in rows]
        exp_values = [r.get("exp") for r in rows]
        mm_values = [r.get("mm_value") for r in rows]
        exp_ranks = [r.get("rank") for r in rows]
        mm_ranks = [r.get("mm_rank") for r in rows]

        exp_cnt = sum(v is not None for v in exp_values)
        mm_cnt = sum(v is not None for v in mm_values)
        rank_cnt = sum(v is not None for v in exp_ranks) + sum(v is not None for v in mm_ranks)
        if len(rows) < 2 and rank_cnt < 2:
            print(colorize("[profile] Skip chart: only one snapshot; use history for trends.", Colors.YELLOW))
            return

        def _fmt(value):
            if value is None:
                return "N/A"
            if isinstance(value, int):
                return f"{value:,}"
            if isinstance(value, float):
                return f"{value:,.2f}" if abs(value) < 1000 else f"{value:,.0f}"
            return str(value)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 5.2))
        fig.suptitle(f"Player Profile by Mode - {player_name}", fontsize=13)

        x = list(range(len(rows)))
        bar_width = 0.38

        # Left: clustered value bars on log scale
        exp_value_points = [(idx, value) for idx, value in enumerate(exp_values) if value is not None and value > 0]
        mm_value_points = [(idx, value) for idx, value in enumerate(mm_values) if value is not None and value > 0]
        exp_value_missing = [idx for idx, value in enumerate(exp_values) if value is None or value <= 0]
        mm_value_missing = [idx for idx, value in enumerate(mm_values) if value is None or value <= 0]

        exp_value_x = [idx - bar_width / 2 for idx, _ in exp_value_points]
        mm_value_x = [idx + bar_width / 2 for idx, _ in mm_value_points]
        exp_value_h = [value for _, value in exp_value_points]
        mm_value_h = [value for _, value in mm_value_points]

        if exp_value_points:
            ax1.bar(exp_value_x, exp_value_h, width=bar_width, label="EXP", color="#1f77b4", alpha=0.9)
        if mm_value_points:
            ax1.bar(mm_value_x, mm_value_h, width=bar_width, label="MM", color="#ff7f0e", alpha=0.9)
        if not exp_value_points and not mm_value_points:
            ax1.text(0.5, 0.5, "No comparable mode values", ha="center", va="center", transform=ax1.transAxes)
        else:
            ax1.set_yscale("log")
            ax1.legend(loc="best")
            min_value = min(exp_value_h + mm_value_h)
            for x_pos, value in zip(exp_value_x, exp_value_h):
                ax1.text(x_pos, value * 1.08, _fmt(value), ha="center", va="bottom", fontsize=8, color="#1f77b4")
            for x_pos, value in zip(mm_value_x, mm_value_h):
                ax1.text(x_pos, value * 1.08, _fmt(value), ha="center", va="bottom", fontsize=8, color="#ff7f0e")
            if exp_value_missing:
                ax1.scatter(
                    [idx - bar_width / 2 for idx in exp_value_missing],
                    [min_value] * len(exp_value_missing),
                    marker="x",
                    s=64,
                    linewidths=1.8,
                    color="#1f77b4",
                    alpha=0.9,
                )
            if mm_value_missing:
                ax1.scatter(
                    [idx + bar_width / 2 for idx in mm_value_missing],
                    [min_value] * len(mm_value_missing),
                    marker="x",
                    s=64,
                    linewidths=1.8,
                    color="#ff7f0e",
                    alpha=0.9,
                )
            fig.text(0.01, 0.006, "X = no data", ha="left", va="bottom", fontsize=8, color="#666666")
        ax1.set_title("Value by Mode (Log Scale)")
        ax1.set_xlabel("Mode")
        ax1.set_ylabel("Value")
        ax1.set_xticks(x)
        ax1.set_xticklabels(mode_labels)
        ax1.grid(True, axis="y", alpha=0.25)

        # Right: clustered rank bars on log scale
        exp_rank_points = [(idx, value) for idx, value in enumerate(exp_ranks) if value is not None and value > 0]
        mm_rank_points = [(idx, value) for idx, value in enumerate(mm_ranks) if value is not None and value > 0]
        exp_rank_missing = [idx for idx, value in enumerate(exp_ranks) if value is None or value <= 0]
        mm_rank_missing = [idx for idx, value in enumerate(mm_ranks) if value is None or value <= 0]

        exp_rank_x = [idx - bar_width / 2 for idx, _ in exp_rank_points]
        mm_rank_x = [idx + bar_width / 2 for idx, _ in mm_rank_points]
        exp_rank_h = [value for _, value in exp_rank_points]
        mm_rank_h = [value for _, value in mm_rank_points]

        has_rank_series = False
        if exp_rank_points:
            ax2.bar(exp_rank_x, [value - 1 for value in exp_rank_h], width=bar_width, bottom=1.0, label="EXP Rank", color="#2ca02c", alpha=0.9)
            has_rank_series = True
        if mm_rank_points:
            ax2.bar(mm_rank_x, [value - 1 for value in mm_rank_h], width=bar_width, bottom=1.0, label="MM Rank", color="#d62728", alpha=0.9)
            has_rank_series = True
        if has_rank_series:
            ax2.set_yscale("log")
            ax2.legend(loc="best")
            for x_pos, value in zip(exp_rank_x, exp_rank_h):
                ax2.text(x_pos, value * 1.08, _fmt(value), ha="center", va="bottom", fontsize=8, color="#2ca02c")
            for x_pos, value in zip(mm_rank_x, mm_rank_h):
                ax2.text(x_pos, value * 1.08, _fmt(value), ha="center", va="bottom", fontsize=8, color="#d62728")
            if exp_rank_missing:
                ax2.scatter(
                    [idx - bar_width / 2 for idx in exp_rank_missing],
                    [1.0] * len(exp_rank_missing),
                    marker="x",
                    s=64,
                    linewidths=1.8,
                    color="#2ca02c",
                    alpha=0.9,
                )
            if mm_rank_missing:
                ax2.scatter(
                    [idx + bar_width / 2 for idx in mm_rank_missing],
                    [1.0] * len(mm_rank_missing),
                    marker="x",
                    s=64,
                    linewidths=1.8,
                    color="#d62728",
                    alpha=0.9,
                )
            fig.text(0.99, 0.006, "X = no data", ha="right", va="bottom", fontsize=8, color="#666666")
        else:
            ax2.text(0.5, 0.5, "No comparable mode ranks", ha="center", va="center", transform=ax2.transAxes)
        ax2.set_title("Rank by Mode (Clustered Log Bars, Lower is Better)")
        ax2.set_xlabel("Mode")
        ax2.set_ylabel("Rank")
        ax2.set_xticks(x)
        ax2.set_xticklabels(mode_labels)
        ax2.grid(True, axis="y", alpha=0.25)

        footer = f"titles={len(titles)} achievements={len(achievements)}"
        fig.text(0.5, 0.02, footer, ha="center", fontsize=9, color="#666666")
        plt.tight_layout(rect=[0, 0.04, 1, 0.96])
        safe_name = re.sub(r"[^\w]", "_", player_name)
        filename = self.get_unique_filename(f"profile_{safe_name}.png", "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor="white")
        plt.close()
        print(colorize(f"[profile] Chart generated: {filepath}", Colors.GREEN))


    setattr(cls, "do_profile", db_safe_operation(do_profile))
    setattr(cls, "_generate_profile_chart", _generate_profile_chart)

