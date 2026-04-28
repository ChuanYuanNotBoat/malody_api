import math
import os

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter


def install(cls, *, colorize, colors, db_safe_operation):
    Colors = colors

    def do_top_chart(self, arg):
        """Generate top players distribution chart (legacy bar style)."""
        args = arg.split()
        limit = 20
        mode = self.current_mode

        if args:
            try:
                if int(args[0]) in self.mode_names:
                    mode = int(args[0])
                    if len(args) > 1:
                        limit = int(args[1])
                else:
                    limit = int(args[0])
                    if len(args) > 1 and int(args[1]) in self.mode_names:
                        mode = int(args[1])
            except ValueError:
                print(colorize("[top_chart] Error: please provide numeric arguments.", Colors.RED))
                return

        if limit <= 0:
            print(colorize("[top_chart] Error: limit must be greater than 0.", Colors.RED))
            return
        if limit > 100:
            print(colorize("[top_chart] Note: limit capped to 100 for readability.", Colors.YELLOW))
            limit = 100

        cursor = self.conn.cursor()
        cursor.execute("SELECT MAX(crawl_time) FROM player_rankings WHERE mode = ?", (mode,))
        latest_time = cursor.fetchone()[0]

        if not latest_time:
            mode_name = self.mode_names.get(mode, "Unknown")
            print(colorize(f"\n[top_chart] No data in mode {mode} ({mode_name}).", Colors.YELLOW))
            return

        cursor.execute(
            """
            SELECT pr.rank, pr.name, pr.acc, pr.exp
            FROM player_rankings pr
            WHERE pr.mode = ? AND pr.crawl_time = ?
            ORDER BY pr.rank
            LIMIT ?
            """,
            (mode, latest_time, limit),
        )
        players = cursor.fetchall()

        if not players:
            mode_name = self.mode_names.get(mode, "Unknown")
            print(colorize(f"\n[top_chart] No players found in mode {mode} ({mode_name}).", Colors.YELLOW))
            return

        ranks = [p[0] for p in players]
        names = [p[1] for p in players]
        accuracies = [float(p[2]) for p in players]
        exps = [float(p[3]) for p in players]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 12))
        fig.patch.set_facecolor("white")

        # Left: accuracy difference bars (legacy visual language)
        max_acc = max(accuracies)
        acc_diffs = [max_acc - acc for acc in accuracies]
        bars = ax1.bar(
            range(len(players)),
            acc_diffs,
            color=plt.cm.viridis(np.linspace(0, 1, len(players))),
        )
        mode_name = self.mode_names.get(mode, "Unknown")
        ax1.set_title(f"Mode {mode} ({mode_name}) Top {limit} Players Accuracy Difference", color="black")
        ax1.set_xlabel("Rank", color="black")
        ax1.set_ylabel("Accuracy Difference from Max (%)", color="black")
        ax1.set_xticks(range(len(players)))
        ax1.set_xticklabels(ranks, rotation=45)
        ax1.tick_params(colors="black")
        ax1.invert_yaxis()

        for i, (bar, acc) in enumerate(zip(bars, accuracies)):
            ax1.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + (max(acc_diffs) * 0.02 if max(acc_diffs) > 0 else 0.01),
                f"{acc:.2f}%",
                ha="center",
                va="bottom",
                fontsize=8,
                color="black",
                rotation=45,
            )
            display_name = names[i] if len(names[i]) <= 12 else names[i][:10] + "..."
            name_y_pos = -0.08 * max(acc_diffs) if max(acc_diffs) > 0 else -0.1
            ax1.text(
                bar.get_x() + bar.get_width() / 2,
                name_y_pos,
                display_name,
                ha="right",
                va="top",
                fontsize=7,
                rotation=60,
                color="black",
            )

        # Right: EXP bars (log scale)
        exp_bars = ax2.bar(
            range(len(players)),
            exps,
            color=plt.cm.plasma(np.linspace(0, 1, len(players))),
        )
        ax2.set_title(f"Mode {mode} ({mode_name}) Top {limit} Players Experience", color="black")
        ax2.set_xlabel("Rank", color="black")
        ax2.set_ylabel("Experience", color="black")
        ax2.set_xticks(range(len(players)))
        ax2.set_xticklabels(ranks, rotation=45)
        ax2.set_yscale("log")
        ax2.tick_params(colors="black")
        ax2.grid(True, which="both", alpha=0.3)

        def log_format_func(value, _pos=None):
            if value >= 1000000:
                return f"{value / 1000000:.1f}M"
            if value >= 1000:
                return f"{value / 1000:.0f}k"
            return f"{value:.0f}"

        ax2.yaxis.set_major_formatter(FuncFormatter(log_format_func))

        min_exp = min(exps) if exps else 1
        max_exp = max(exps) if exps else 1000
        min_power = math.floor(math.log10(max(min_exp, 1)))
        max_power = math.ceil(math.log10(max_exp))
        tick_values = []
        for power in range(int(min_power), int(max_power) + 1):
            base = 10 ** power
            tick_values.extend(
                [base * mult for mult in (1, 2, 5) if min_exp <= base * mult <= max_exp * 1.1]
            )
        if tick_values:
            ax2.set_yticks(tick_values)

        for i, (bar, exp_val) in enumerate(zip(exp_bars, exps)):
            ax2.text(
                bar.get_x() + bar.get_width() / 2,
                exp_val * 1.08,
                f"{exp_val:.0f}",
                ha="center",
                va="bottom",
                fontsize=8,
                color="black",
                rotation=45,
            )
            display_name = names[i] if len(names[i]) <= 12 else names[i][:10] + "..."
            name_y_pos = (10 ** (math.log10(min_exp) - 0.3)) if min_exp > 0 else 1
            ax2.text(
                bar.get_x() + bar.get_width() / 2,
                name_y_pos,
                display_name,
                ha="right",
                va="top",
                fontsize=7,
                rotation=60,
                color="black",
            )

        bottom_margin = 0.25 + 0.01 * limit
        plt.subplots_adjust(bottom=min(bottom_margin, 0.4), top=0.9, wspace=0.3)
        plt.tight_layout()

        filename = self.get_unique_filename(f"top_players_mode{mode}.png", "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor="white", bbox_inches="tight")
        plt.close()

        print(colorize(f"\n[top_chart] Chart generated: {filepath}", Colors.GREEN))

    setattr(cls, "do_top_chart", db_safe_operation(do_top_chart))
