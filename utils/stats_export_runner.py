import copy
import os
from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

from utils.stats_update_runner import parse_cli_options, split_cli_args


ColorizeFn = Callable[[str, str], str]
TimeRangeParserFn = Callable[[str], Optional[dict]]
FilenameFn = Callable[[str, str], str]


@dataclass
class ExportRequest:
    export_type: str
    mode: Optional[int]
    limit: int
    players: list[str]
    time_range: Optional[dict]


def parse_export_request(
    arg: str,
    parse_time_range: TimeRangeParserFn,
    colorize: ColorizeFn,
    red: str,
) -> Optional[ExportRequest]:
    args = split_cli_args(arg, colorize, red)
    if args is None:
        return None
    if not args:
        print(colorize("Error: export type is required", red))
        return None

    export_type = args[0].lower()
    opts = parse_cli_options(args[1:], colorize, red)
    if opts is None:
        return None

    mode = None
    if "--mode" in opts and isinstance(opts["--mode"], str):
        try:
            mode = int(opts["--mode"])
        except Exception:
            print(colorize("Error: --mode must be an integer", red))
            return None

    limit = 1000
    if "--limit" in opts and isinstance(opts["--limit"], str):
        try:
            limit = int(opts["--limit"])
            if limit <= 0:
                raise ValueError()
        except Exception:
            print(colorize("Error: --limit must be a positive integer", red))
            return None

    players: list[str] = []
    if "--players" in opts and isinstance(opts["--players"], str):
        players = [x.strip() for x in opts["--players"].split(",") if x.strip()]

    time_range = None
    if "--time-range" in opts and isinstance(opts["--time-range"], str):
        time_range = parse_time_range(opts["--time-range"])
        if not time_range:
            print(colorize("Error: invalid --time-range, expected 30d/8w/6m/1y/2025-01-01", red))
            return None

    return ExportRequest(
        export_type=export_type,
        mode=mode,
        limit=limit,
        players=players,
        time_range=time_range,
    )


def run_export(
    request: ExportRequest,
    conn,
    selector,
    output_dir: str,
    unique_filename: FilenameFn,
    colorize: ColorizeFn,
    green: str,
    yellow: str,
    red: str,
) -> bool:
    export_type = request.export_type
    mode = request.mode
    limit = request.limit
    players = request.players
    time_range = request.time_range

    if export_type == "chart":
        run_selector = copy.deepcopy(selector)
        if mode is not None:
            run_selector.set_filters(modes=[mode])
            run_selector.current_mode = mode
        if players:
            run_selector.set_filters(players=players)
        if time_range:
            run_selector.set_filters(time_range=time_range)

        where, params = run_selector.build_chart_sql_where("c")
        query = f"""
        SELECT c.cid, c.sid, s.title, s.artist, c.version, c.level, c.status,
               c.creator_name, c.stabled_by_name, c.heat, c.donate_count, c.play_count,
               c.last_updated, c.mode
        FROM charts c
        JOIN songs s ON c.sid = s.sid
        WHERE {where}
        ORDER BY c.last_updated DESC, c.cid DESC
        LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=params + [limit])
        filename = unique_filename("charts_export.csv", "csv")

    elif export_type == "top":
        use_mode = mode if mode is not None else selector.current_mode
        params = [use_mode, use_mode]
        player_filter = ""
        if players:
            placeholders = ",".join(["?"] * len(players))
            player_filter = f" AND pr.name IN ({placeholders})"
            params.extend(players)

        query = f"""
        WITH latest AS (
          SELECT MAX(crawl_time) AS ct FROM player_rankings WHERE mode = ?
        )
        SELECT pr.rank, pr.name, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc, pr.crawl_time, pr.mode
        FROM player_rankings pr
        WHERE pr.mode = ?
          AND pr.crawl_time = (SELECT ct FROM latest)
          {player_filter}
        ORDER BY pr.rank ASC
        LIMIT ?
        """
        params.append(limit)
        df = pd.read_sql_query(query, conn, params=params)
        filename = unique_filename("players_top_export.csv", "csv")

    elif export_type == "history":
        use_mode = mode if mode is not None else selector.current_mode
        params = [use_mode]
        player_filter = ""
        if players:
            placeholders = ",".join(["?"] * len(players))
            player_filter = (
                f" AND (pr.name IN ({placeholders}) "
                f"OR pr.player_id IN (SELECT player_id FROM player_aliases WHERE alias IN ({placeholders})))"
            )
            params.extend(players)
            params.extend(players)

        time_filter = ""
        if time_range:
            time_filter = " AND pr.crawl_time BETWEEN ? AND ?"
            params.extend([time_range["start"], time_range["end"]])

        query = f"""
        SELECT pr.player_id, pr.name, pr.mode, pr.rank, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc, pr.crawl_time
        FROM player_rankings pr
        WHERE pr.mode = ?
          {player_filter}
          {time_filter}
        ORDER BY pr.crawl_time DESC, pr.rank ASC
        LIMIT ?
        """
        params.append(limit)
        df = pd.read_sql_query(query, conn, params=params)
        filename = unique_filename("players_history_export.csv", "csv")

    elif export_type == "song":
        params = []
        having_mode = ""
        if mode is not None:
            having_mode = " AND SUM(CASE WHEN c.mode = ? THEN 1 ELSE 0 END) > 0"
            params.append(mode)

        query = f"""
        SELECT s.sid, s.title, s.artist,
               COUNT(DISTINCT c.cid) AS chart_count,
               COUNT(DISTINCT CASE WHEN c.status = 2 THEN c.cid END) AS stable_count,
               COUNT(DISTINCT c.mode) AS mode_count,
               MAX(c.last_updated) AS latest_chart_update
        FROM songs s
        LEFT JOIN charts c ON s.sid = c.sid
        GROUP BY s.sid, s.title, s.artist
        HAVING 1=1 {having_mode}
        ORDER BY stable_count DESC, chart_count DESC, s.sid ASC
        LIMIT ?
        """
        params.append(limit)
        df = pd.read_sql_query(query, conn, params=params)
        filename = unique_filename("songs_export.csv", "csv")

    elif export_type == "profile":
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(player_profiles)")
        profile_columns = [row[1] for row in cursor.fetchall()]
        if not profile_columns:
            print(colorize("Error: player_profiles table not found; cannot export profile", red))
            return False

        preferred = [
            "player_id",
            "uid",
            "avatar_url",
            "country",
            "bio",
            "join_date",
            "last_crawled",
            "needs_update",
        ]
        selected = [c for c in preferred if c in profile_columns]
        if "player_id" not in selected:
            selected.insert(0, "player_id")

        selected_sql = ", ".join([f"pp.{c}" for c in selected])
        params = []
        player_filter = ""
        if players:
            placeholders = ",".join(["?"] * len(players))
            player_filter = f"WHERE pi.current_name IN ({placeholders}) OR pa.alias IN ({placeholders})"
            params.extend(players)
            params.extend(players)

        query = f"""
        SELECT pi.current_name, {selected_sql}
        FROM player_profiles pp
        LEFT JOIN player_identity pi ON pp.player_id = pi.player_id
        LEFT JOIN player_aliases pa ON pp.player_id = pa.player_id
        {player_filter}
        GROUP BY pp.player_id
        ORDER BY pp.player_id DESC
        LIMIT ?
        """
        params.append(limit)
        df = pd.read_sql_query(query, conn, params=params)
        filename = unique_filename("profiles_export.csv", "csv")

    else:
        print(colorize(f"Export type '{export_type}' is not implemented", yellow))
        return False

    filepath = os.path.join(output_dir, filename)
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(colorize(f"Exported {export_type} data to: {filepath}", green))
    return True
