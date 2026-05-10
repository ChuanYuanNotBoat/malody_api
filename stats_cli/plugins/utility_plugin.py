import os
import shlex
from datetime import datetime

try:
    from malody_api.core.services import PlayerService as _PkgPlayerService
except Exception:
    _PkgPlayerService = None


def install(cls, *, colorize, colors, get_separator, db_safe_operation):
    def do_ls(self, arg):
        """
        列出当前目录的文件和目录
        """
        path = arg if arg else "."
        try:
            if os.path.exists(path):
                items = os.listdir(path)
                print(colorize(f"\n{path} 目录内容:", colors.CYAN))
                print(get_separator())
                for item in items:
                    full_path = os.path.join(path, item)
                    if os.path.isdir(full_path):
                        print(colorize(f"[目录] {item}/", colors.BLUE))
                    else:
                        size = os.path.getsize(full_path)
                        print(f"[文件] {item} ({size} 字节)")
            else:
                print(colorize(f"路径不存在: {path}", colors.RED))
        except Exception as e:
            print(colorize(f"列出目录时出错: {e}", colors.RED))

    def do_mode(self, arg):
        """
        设置或查看当前模式（支持 * 表示所有模式）
        """
        if not arg:
            mode_name = self.mode_names.get(self.current_mode, "未知")
            print(colorize(f"\n当前模式: {self.current_mode} ({mode_name})", colors.CYAN))
            print(colorize(f"当前筛选: {self.selector.get_current_selection()}", colors.YELLOW))
            return

        if arg == "*":
            self.current_mode = -1
            self.selector.current_mode = -1
            self.selector.set_filters(modes=[])
            print(colorize("\n已切换到所有模式", colors.GREEN))
            return

        try:
            mode = int(arg)
            if mode not in self.mode_names or mode == -1:
                print(colorize("错误: 模式必须在 0-9 之间，或使用 * 表示所有模式", colors.RED))
                return
            self.current_mode = mode
            self.selector.current_mode = mode
            self.selector.set_filters(modes=[mode])
            mode_name = self.mode_names.get(mode, "未知")
            print(colorize(f"\n已切换到模式: {mode} ({mode_name})", colors.GREEN))
        except ValueError:
            print(colorize("错误: 请输入有效的模式数字(0-9)或 *", colors.RED))

    def do_exit(self, arg):
        """退出程序"""
        print(colorize("\n感谢使用 Malody 排行榜数据可视化工具!", colors.CYAN))
        self.cleanup()
        return True

    def do_quit(self, arg):
        """退出程序"""
        return self.do_exit(arg)

    def do_reload(self, arg):
        """
        Reload plugin modules/commands without restarting CLI.
        Usage:
            reload
            reload all
            reload module <name>
            reload command <name>
        """
        from stats_cli.plugins.registry import reload_plugins

        def _print_reload_usage():
            print(colorize("Usage: reload [all|module <name>|command <name>]", colors.CYAN))
            print("Examples:")
            print("  reload all")
            print("  reload module help")
            print("  reload command ls")

        raw = (arg or "").strip()
        mode = "all"
        target = None

        if raw:
            try:
                tokens = shlex.split(raw)
            except ValueError as exc:
                print(colorize(f"Failed to parse arguments: {exc}", colors.RED))
                return

            head = tokens[0].lower() if tokens else ""
            if head in {"?", "help", "-h", "--help"} and len(tokens) == 1:
                _print_reload_usage()
                return
            if head in {"all", "*"} and len(tokens) == 1:
                mode = "all"
            elif head in {"module", "m", "mod", "moudle"} and len(tokens) == 2:
                mode = "module"
                target = tokens[1]
            elif head in {"command", "cmd", "c"} and len(tokens) == 2:
                mode = "command"
                target = tokens[1]
            elif len(tokens) == 1:
                guess = tokens[0]
                if hasattr(self.__class__, f"do_{guess.lower()}"):
                    mode = "command"
                else:
                    mode = "module"
                target = guess
            else:
                _print_reload_usage()
                return

        if mode == "all":
            result = reload_plugins(self.__class__)
        elif mode == "module":
            result = reload_plugins(self.__class__, module_name=target)
        else:
            result = reload_plugins(self.__class__, command_name=target)

        if result.get("ok"):
            print(colorize(result.get("message", "Reload done"), colors.GREEN))
        else:
            print(colorize(result.get("message", "Reload failed"), colors.RED))
            for hint in result.get("hints", []) or []:
                print(colorize(f"Hint: {hint}", colors.YELLOW))

    def do_mm_stats(self, arg):
        """
        查看 MM/MMR 统计概览（与 API /players/mm/stats 对齐）

        用法: mm_stats [mm_limit]
        参数:
        mm_limit - 可选，MM 榜 topN 玩家并集范围，默认 200
        """
        try:
            mm_limit = int(arg.strip()) if arg and arg.strip() else 200
            if mm_limit <= 0:
                print(colorize("错误: mm_limit 必须大于 0", colors.RED))
                return
        except ValueError:
            print(colorize("错误: mm_limit 需要是整数", colors.RED))
            return

        data = None
        if _PkgPlayerService is not None:
            try:
                service = _PkgPlayerService()
                data = service.get_mm_stats(mm_limit=mm_limit)
            except Exception:
                data = None
        if not data:
            # Fallback for direct script mode where `malody_api` package name may be unavailable.
            data = self._build_mm_stats_fallback(mm_limit)
        if not data:
            print(colorize("未获取到 MM/MMR 统计数据", colors.YELLOW))
            return

        counts = data.get("counts", {})
        freshness = data.get("freshness", {})
        tracked = data.get("tracked_players", {})
        mm_modes = data.get("mm_latest_snapshot_by_mode", [])
        mmr_sources = data.get("mmr_samples_by_source", [])

        print(colorize("\nMM/MMR 统计概览", colors.CYAN))
        print(get_separator())
        print(f"player_rankings_mm: {counts.get('player_rankings_mm')}")
        print(f"player_mmr_samples: {counts.get('player_mmr_samples')}")
        print(f"player_mmr_daily: {counts.get('player_mmr_daily')}")
        print(f"MM latest: {freshness.get('player_rankings_mm_max_crawl_time')}")
        print(f"MMR latest: {freshness.get('player_mmr_samples_max_crawl_time')}")
        print(get_separator())
        print(
            "tracked players: "
            f"union={tracked.get('union_players_count')} "
            f"(manual={tracked.get('manual_players_count')}, mm_top={tracked.get('mm_top_players_count')}, "
            f"overlap={tracked.get('overlap_count')}, mm_limit={tracked.get('mm_limit')})"
        )
        print(get_separator())
        print("MM latest snapshot by mode:")
        for row in mm_modes:
            print(
                f"mode={row.get('mode')} rows={row.get('rows')} "
                f"dup_rank={row.get('dup_rank')} dup_uid={row.get('dup_uid')} "
                f"rank=[{row.get('min_rank')},{row.get('max_rank')}]"
            )
        if mmr_sources:
            print(get_separator())
            print("MMR sources:")
            for row in mmr_sources:
                print(
                    f"{row.get('source')}: samples={row.get('sample_count')} "
                    f"players={row.get('player_count')}"
                )

    def _build_mm_stats_fallback(self, mm_limit):
        conn = self.conn
        cursor = conn.cursor()

        def table_exists(table_name):
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
                (table_name,),
            )
            return cursor.fetchone() is not None

        def scalar(sql, params=()):
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return row[0] if row else None

        counts = {}
        for table in ["player_rankings_mm", "player_mmr_samples", "player_mmr_daily"]:
            counts[table] = int(scalar(f"SELECT COUNT(*) FROM {table}") or 0) if table_exists(table) else None

        freshness = {}
        if table_exists("player_rankings_mm"):
            freshness["player_rankings_mm_max_crawl_time"] = scalar("SELECT MAX(crawl_time) FROM player_rankings_mm")
        if table_exists("player_mmr_samples"):
            freshness["player_mmr_samples_max_crawl_time"] = scalar("SELECT MAX(crawl_time) FROM player_mmr_samples")

        manual_players = []
        if os.path.exists("players.txt"):
            try:
                with open("players.txt", "r", encoding="utf-8") as f:
                    for raw in f:
                        line = raw.strip()
                        if line and not line.startswith("#") and line.isdigit():
                            manual_players.append(line)
            except Exception:
                manual_players = []
        manual_set = set(manual_players)

        mm_top = set()
        if table_exists("player_rankings_mm"):
            cursor.execute(
                """
                WITH latest AS (
                    SELECT mode, MAX(crawl_time) AS ct
                    FROM player_rankings_mm
                    GROUP BY mode
                )
                SELECT DISTINCT r.uid
                FROM player_rankings_mm r
                JOIN latest l ON l.mode = r.mode AND l.ct = r.crawl_time
                WHERE r.rank <= ?
                  AND r.uid IS NOT NULL
                  AND r.uid != ''
                  AND r.uid != '0'
                """,
                (mm_limit,),
            )
            mm_top = {str(row[0]) for row in cursor.fetchall() if row and row[0]}

        tracked = {
            "mm_limit": mm_limit,
            "manual_players_count": len(manual_set),
            "mm_top_players_count": len(mm_top),
            "union_players_count": len(manual_set | mm_top),
            "overlap_count": len(manual_set & mm_top),
        }

        mm_modes = []
        if table_exists("player_rankings_mm"):
            cursor.execute(
                """
                WITH latest AS (
                    SELECT mode, MAX(crawl_time) AS ct
                    FROM player_rankings_mm
                    GROUP BY mode
                )
                SELECT r.mode,
                       COUNT(*) AS rows_count,
                       COUNT(DISTINCT r.uid) AS uid_distinct,
                       COUNT(DISTINCT r.rank) AS rank_distinct,
                       MIN(r.rank),
                       MAX(r.rank)
                FROM player_rankings_mm r
                JOIN latest l ON l.mode = r.mode AND l.ct = r.crawl_time
                GROUP BY r.mode
                ORDER BY r.mode
                """
            )
            for row in cursor.fetchall():
                rows_count = int(row[1] or 0)
                uid_distinct = int(row[2] or 0)
                rank_distinct = int(row[3] or 0)
                mm_modes.append(
                    {
                        "mode": row[0],
                        "rows": rows_count,
                        "dup_rank": max(rows_count - rank_distinct, 0),
                        "dup_uid": max(rows_count - uid_distinct, 0),
                        "min_rank": row[4],
                        "max_rank": row[5],
                    }
                )

        mmr_sources = []
        if table_exists("player_mmr_samples"):
            cursor.execute(
                """
                SELECT source, COUNT(*) AS sample_count, COUNT(DISTINCT uid) AS player_count
                FROM player_mmr_samples
                GROUP BY source
                ORDER BY sample_count DESC
                """
            )
            mmr_sources = [
                {"source": row[0], "sample_count": int(row[1] or 0), "player_count": int(row[2] or 0)}
                for row in cursor.fetchall()
            ]

        return {
            "counts": counts,
            "freshness": freshness,
            "tracked_players": tracked,
            "mm_latest_snapshot_by_mode": mm_modes,
            "mmr_samples_by_source": mmr_sources,
            "generated_at": datetime.now().isoformat(),
        }

    setattr(cls, "do_ls", db_safe_operation(do_ls))
    setattr(cls, "do_mode", do_mode)
    setattr(cls, "do_exit", do_exit)
    setattr(cls, "do_quit", do_quit)
    setattr(cls, "do_reload", do_reload)
    setattr(cls, "do_mm_stats", db_safe_operation(do_mm_stats))
    setattr(cls, "_build_mm_stats_fallback", _build_mm_stats_fallback)
    setattr(cls, "do_q", do_quit)
    setattr(cls, "do_e", do_exit)

