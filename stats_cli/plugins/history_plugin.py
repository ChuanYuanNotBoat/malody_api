import os
from datetime import datetime, timedelta

import matplotlib.dates as mdates
import matplotlib.pyplot as plt


def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors

    def _dedupe_by_day(rows, day_getter):
        deduped = []
        last_day = None
        for row in rows:
            day_key = day_getter(row)
            if deduped and day_key == last_day:
                deduped[-1] = row
            else:
                deduped.append(row)
                last_day = day_key
        return deduped

    def _fmt_num(v):
        if isinstance(v, int):
            return f"{v:,}"
        if isinstance(v, float):
            return f"{v:,.2f}"
        return str(v)

    def do_history(self, arg):
        """Show player history and generate chart."""
        args = arg.split()
        if not args:
            print(colorize("Error: please provide player name.", Colors.RED))
            return

        player_name = args[0]
        mode = self.current_mode
        days = 30
        metric = "exp_rank"
        mode_set = False
        days_set = False

        for tok in args[1:]:
            lower = tok.lower()
            if lower in ("exp_rank", "mm_rank", "mmr"):
                metric = lower
                continue
            try:
                val = int(tok)
            except ValueError:
                print(colorize("Error: expected [mode] [days] [exp_rank|mm_rank|mmr].", Colors.RED))
                return
            if not mode_set:
                if val not in self.mode_names or val == -1:
                    print(colorize("Error: mode must be in 0-9.", Colors.RED))
                    return
                mode = val
                mode_set = True
                continue
            if not days_set:
                if val <= 0:
                    print(colorize("Error: days must be > 0.", Colors.RED))
                    return
                days = val
                days_set = True
                continue
            print(colorize("Error: too many arguments. Use history <player> [mode] [days] [metric].", Colors.RED))
            return

        cursor = self.conn.cursor()
        if metric in ("mm_rank", "mmr"):
            table_name = "player_rankings_mm" if metric == "mm_rank" else "player_mmr_daily"
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
                (table_name,),
            )
            if not cursor.fetchone():
                print(colorize(f"Table not found: {table_name}", Colors.YELLOW))
                return

        if player_name.isdigit():
            cursor.execute("SELECT player_id FROM player_identity WHERE uid = ?", (player_name,))
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
            print(colorize(f"\nPlayer not found: {player_name}", Colors.YELLOW))
            return

        player_id = result[0]
        uid = player_name if player_name.isdigit() else None
        if not uid:
            cursor.execute("SELECT uid FROM player_identity WHERE player_id = ?", (player_id,))
            uid_row = cursor.fetchone()
            if uid_row and uid_row[0]:
                uid = str(uid_row[0])

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        allowed_modes = list(self.selector.filters.get("modes") or [])

        history_data = []
        y_label = "Rank"
        chart_title = f"Player {player_name} Ranking History"
        line_series = []
        line_dates = []
        print_formatter = None

        if metric == "mmr":
            if not uid:
                print(colorize(f"\nPlayer {player_name} has no UID; cannot query MMR history.", Colors.YELLOW))
                return
            if mode == -1:
                if allowed_modes:
                    placeholders = ",".join(["?"] * len(allowed_modes))
                    cursor.execute(
                        f"""
                        SELECT mode
                        FROM player_mmr_daily
                        WHERE uid = ? AND mode IN ({placeholders})
                        ORDER BY day DESC, sample_time DESC, mode ASC
                        LIMIT 1
                        """,
                        [uid, *allowed_modes],
                    )
                else:
                    cursor.execute(
                        "SELECT mode FROM player_mmr_daily WHERE uid = ? ORDER BY day DESC, sample_time DESC, mode ASC LIMIT 1",
                        (uid,),
                    )
                mode_row = cursor.fetchone()
                if mode_row:
                    mode = mode_row[0]
            if mode == -1:
                print(colorize(f"\nPlayer {player_name} has no available mode for MMR data.", Colors.YELLOW))
                return

            cursor.execute(
                """
                SELECT day, mmr, sample_time
                FROM player_mmr_daily
                WHERE uid = ? AND mode = ? AND day >= ?
                ORDER BY day, sample_time
                """,
                (uid, mode, start_date.date().isoformat()),
            )
            raw_rows = cursor.fetchall()
            dedup_rows = _dedupe_by_day(raw_rows, lambda row: row[0])
            history_data = [(row[0], row[1]) for row in dedup_rows]

            line_dates = [
                datetime.strptime(row[0], "%Y-%m-%d") if isinstance(row[0], str) else row[0]
                for row in history_data
            ]
            line_series = [row[1] for row in history_data]
            y_label = "MMR"
            chart_title = f"Player {player_name} MMR History"
            print_formatter = lambda row: f"{row[0]}: MMR {row[1]}"
        else:
            table = "player_rankings_mm" if metric == "mm_rank" else "player_rankings"
            if mode == -1:
                if allowed_modes:
                    placeholders = ",".join(["?"] * len(allowed_modes))
                    cursor.execute(
                        f"""
                        SELECT mode
                        FROM {table}
                        WHERE player_id = ? AND mode IN ({placeholders})
                        ORDER BY crawl_time DESC, mode ASC
                        LIMIT 1
                        """,
                        [player_id, *allowed_modes],
                    )
                else:
                    cursor.execute(
                        f"SELECT mode FROM {table} WHERE player_id = ? ORDER BY crawl_time DESC, mode ASC LIMIT 1",
                        (player_id,),
                    )
                mode_row = cursor.fetchone()
                if mode_row:
                    mode = mode_row[0]
            if mode == -1:
                print(colorize(f"\nPlayer {player_name} has no available mode data.", Colors.YELLOW))
                return

            cursor.execute(
                f"""
                SELECT pr.rank, pr.crawl_time
                FROM {table} pr
                WHERE pr.player_id = ? AND pr.mode = ? AND pr.crawl_time >= ?
                ORDER BY pr.crawl_time
                """,
                (player_id, mode, start_date),
            )
            raw_rows = cursor.fetchall()
            dedup_rows = _dedupe_by_day(
                raw_rows,
                lambda row: row[1].date() if hasattr(row[1], "date") else str(row[1])[:10],
            )
            history_data = dedup_rows
            line_dates = [row[1] for row in history_data]
            line_series = [row[0] for row in history_data]
            if metric == "mm_rank":
                chart_title = f"Player {player_name} MM Rank History"
            print_formatter = lambda row: f"{row[1].strftime('%Y-%m-%d') if hasattr(row[1], 'strftime') else str(row[1])}: #{row[0]}"

        if not history_data:
            mode_name = self.mode_names.get(mode, "Unknown")
            print(colorize(f"\nNo {metric} data for {player_name} in mode {mode} ({mode_name}) during last {days} days.", Colors.YELLOW))
            return

        if len(history_data) < 2:
            print(colorize("\n[history] Data points < 2; trend interpretation is limited.", Colors.YELLOW))
            print(get_separator())
            for row in history_data:
                print(print_formatter(row))

        fig, ax = plt.subplots(figsize=(11, 5.5))
        marker = "o" if len(line_series) <= 60 else None
        ax.plot(line_dates, line_series, "-", linewidth=2.0, marker=marker, markersize=3.5, color="#1f77b4")

        if metric in ("exp_rank", "mm_rank"):
            ax.invert_yaxis()

        mode_name = self.mode_names.get(mode, "Unknown")
        ax.set_title(f"{chart_title} (Mode {mode} - {mode_name})")
        ax.set_xlabel("Date")
        ax.set_ylabel(y_label)
        ax.grid(True, alpha=0.25)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate()

        # Highlight latest point and show concise summary.
        latest_x = line_dates[-1]
        latest_y = line_series[-1]
        ax.scatter([latest_x], [latest_y], s=36, color="#d62728", zorder=3)
        ax.annotate(
            f"latest: {_fmt_num(latest_y)}",
            xy=(latest_x, latest_y),
            xytext=(6, 8),
            textcoords="offset points",
            fontsize=8,
            color="#d62728",
        )

        start_y = line_series[0]
        delta = latest_y - start_y
        if metric in ("exp_rank", "mm_rank"):
            summary = f"start={_fmt_num(start_y)}  end={_fmt_num(latest_y)}  delta={_fmt_num(delta)} (negative is better)"
        else:
            summary = f"start={_fmt_num(start_y)}  end={_fmt_num(latest_y)}  delta={_fmt_num(delta)}"
        fig.text(0.01, 0.01, summary, ha="left", va="bottom", fontsize=8, color="#666666")

        if metric == "exp_rank":
            base_filename = f"player_history_{player_name}_mode{mode}.png"
        else:
            base_filename = f"player_history_{player_name}_mode{mode}_{metric}.png"

        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.tight_layout(rect=[0, 0.03, 1, 1])
        plt.savefig(filepath, dpi=150, facecolor="white")
        plt.close()

        print(colorize(f"\n\u5df2\u751f\u6210\u5386\u53f2\u56fe\u8868: {filepath}", Colors.GREEN))
        print(colorize(f"\n{player_name} recent changes ({metric}):", Colors.CYAN))
        print(get_separator())
        recent_rows = history_data[-10:] if len(history_data) > 10 else history_data
        for row in recent_rows:
            print(print_formatter(row))

    setattr(cls, "do_history", db_safe_operation(do_history))
