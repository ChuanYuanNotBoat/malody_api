import copy
import os
from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

from utils.stats_update_runner import parse_cli_options, split_cli_args
from utils.stats_xlsx_formatter import (
  apply_change_conditional_formatting,
  autosize_openpyxl_sheet,
)

ColorizeFn = Callable[[str, str], str]
TimeRangeParserFn = Callable[[str], Optional[dict]]
FilenameFn = Callable[[str, str], str]

SUPPORTED_EXPORT_FORMATS = {"csv", "xlsx"}


def _build_player_lookup_filter(players: list[str], table_alias: str) -> tuple[str, list[object]]:
    conditions: list[str] = []
    params: list[object] = []

    for player in players:
        if player.isdigit():
            conditions.append(
                "("
                f"{table_alias}.player_id IN (SELECT player_id FROM player_identity WHERE uid = ?)"
                f" OR {table_alias}.name IN (SELECT current_name FROM player_identity WHERE uid = ?)"
                f" OR {table_alias}.player_id IN ("
                "SELECT pa.player_id FROM player_aliases pa "
                "JOIN player_identity pi ON pa.player_id = pi.player_id "
                "WHERE pi.uid = ?)"
                ")"
            )
            params.extend([player, player, player])
        else:
            conditions.append(
                "("
                f"{table_alias}.name IN (SELECT current_name FROM player_identity WHERE current_name = ?)"
                f" OR {table_alias}.name = ?"
                f" OR {table_alias}.player_id IN (SELECT player_id FROM player_aliases WHERE alias = ?)"
                ")"
            )
            params.extend([player, player, player])

    return (" OR ".join(conditions), params)


def _build_profile_lookup_filter(players: list[str]) -> tuple[str, list[object]]:
    conditions: list[str] = []
    params: list[object] = []

    for player in players:
        if player.isdigit():
            conditions.append(
                "("
                "pi.uid = ?"
                " OR pp.uid = ?"
                " OR pp.player_id IN (SELECT player_id FROM player_identity WHERE uid = ?)"
                ")"
            )
            params.extend([player, player, player])
        else:
            conditions.append(
                "("
                "pi.current_name = ?"
                " OR pa.alias = ?"
                ")"
            )
            params.extend([player, player])

    return (" OR ".join(conditions), params)


@dataclass
class ExportRequest:
    export_type: str
    mode: Optional[int]
    limit: int
    players: list[str]
    time_range: Optional[dict]
    output_format: str = "csv"
    with_summary: bool = False
    with_metadata: bool = False


@dataclass
class ExportPayload:
    dataframe: pd.DataFrame
    base_filename: str
    sheet_name: str
    metadata: dict[str, object]


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

    output_format = "csv"
    if "--format" in opts and isinstance(opts["--format"], str):
        output_format = opts["--format"].strip().lower()
        if output_format not in SUPPORTED_EXPORT_FORMATS:
            print(colorize("Error: --format must be csv or xlsx", red))
            return None

    with_summary = bool(opts.get("--with-summary", False))
    with_metadata = bool(opts.get("--with-metadata", False))

    return ExportRequest(
        export_type=export_type,
        mode=mode,
        limit=limit,
        players=players,
        time_range=time_range,
        output_format=output_format,
        with_summary=with_summary,
        with_metadata=with_metadata,
    )


def _build_export_payload(
    request: ExportRequest,
    conn,
    selector,
    colorize: ColorizeFn,
    red: str,
    yellow: str,
) -> Optional[ExportPayload]:
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
        base_filename = "charts_export"
        sheet_name = "charts"

    elif export_type == "top":
        use_mode = mode if mode is not None else selector.current_mode
        params = [use_mode, use_mode]
        player_filter = ""
        if players:
            lookup_filter, lookup_params = _build_player_lookup_filter(players, "pr")
            player_filter = f" AND ({lookup_filter})"
            params.extend(lookup_params)

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
        base_filename = "players_top_export"
        sheet_name = "top_players"

    elif export_type == "history":
        use_mode = mode if mode is not None else selector.current_mode
        params = [use_mode]
        player_filter = ""
        if players:
            lookup_filter, lookup_params = _build_player_lookup_filter(players, "pr")
            player_filter = f" AND ({lookup_filter})"
            params.extend(lookup_params)

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
        base_filename = "players_history_export"
        sheet_name = "history"

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
        base_filename = "songs_export"
        sheet_name = "songs"

    elif export_type == "profile":
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(player_profiles)")
        profile_columns = [row[1] for row in cursor.fetchall()]
        if not profile_columns:
            print(colorize("Error: player_profiles table not found; cannot export profile", red))
            return None

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
            lookup_filter, lookup_params = _build_profile_lookup_filter(players)
            player_filter = f"WHERE {lookup_filter}"
            params.extend(lookup_params)

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
        base_filename = "profiles_export"
        sheet_name = "profiles"

    else:
        print(colorize(f"Export type '{export_type}' is not implemented", yellow))
        return None

    metadata = {
        "export_type": export_type,
        "format": request.output_format,
        "row_count": len(df),
        "generated_at": pd.Timestamp.now().isoformat(),
        "mode": mode if mode is not None else "",
        "players": ",".join(players) if players else "",
        "time_range": str(time_range) if time_range else "",
        "limit": limit,
    }
    return ExportPayload(
        dataframe=df,
        base_filename=base_filename,
        sheet_name=sheet_name,
        metadata=metadata,
    )


def _build_summary_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for col in df.columns:
        series = df[col]
        row: dict[str, object] = {
            "column": col,
            "dtype": str(series.dtype),
            "non_null": int(series.notna().sum()),
            "null_count": int(series.isna().sum()),
            "unique_count": int(series.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(series):
            row.update(
                {
                    "min": float(series.min()) if row["non_null"] else None,
                    "max": float(series.max()) if row["non_null"] else None,
                    "mean": float(series.mean()) if row["non_null"] else None,
                }
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _write_xlsx_file(filepath: str, payload: ExportPayload, request: ExportRequest) -> None:
    last_error: Optional[Exception] = None
    for engine in ("openpyxl", "xlsxwriter", None):
        try:
            with pd.ExcelWriter(filepath, engine=engine) as writer:
                payload.dataframe.to_excel(writer, sheet_name=payload.sheet_name, index=False)

                if request.with_metadata:
                    meta_df = pd.DataFrame(
                        [{"key": key, "value": value} for key, value in payload.metadata.items()]
                    )
                    meta_df.to_excel(writer, sheet_name="metadata", index=False)

                if request.with_summary:
                    summary_df = _build_summary_dataframe(payload.dataframe)
                    summary_df.to_excel(writer, sheet_name="summary", index=False)

                main_sheet = writer.sheets.get(payload.sheet_name)
                if main_sheet is not None:
                    apply_change_conditional_formatting(main_sheet, payload.dataframe)

                for worksheet in writer.sheets.values():
                    freeze_attr = getattr(worksheet, "freeze_panes", None)
                    if callable(freeze_attr):
                        try:
                            freeze_attr(1, 0)
                        except Exception:
                            pass
                    elif freeze_attr is not None:
                        try:
                            worksheet.freeze_panes = "A2"
                        except Exception:
                            pass
                    autosize_openpyxl_sheet(worksheet)
            return
        except Exception as exc:
            last_error = exc
            continue

    raise RuntimeError(
        "Unable to write xlsx file. Please install openpyxl or xlsxwriter."
    ) from last_error


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
    payload = _build_export_payload(
        request=request,
        conn=conn,
        selector=selector,
        colorize=colorize,
        red=red,
        yellow=yellow,
    )
    if payload is None:
        return False

    if request.output_format not in SUPPORTED_EXPORT_FORMATS:
        print(colorize(f"Error: unsupported format '{request.output_format}'", red))
        return False

    ext = request.output_format
    filename = unique_filename(f"{payload.base_filename}.{ext}", ext)
    filepath = os.path.join(output_dir, filename)

    try:
        if request.output_format == "csv":
            payload.dataframe.to_csv(filepath, index=False, encoding="utf-8-sig")
        else:
            _write_xlsx_file(filepath, payload, request)
    except Exception as exc:
        print(colorize(f"Error: failed to export {request.output_format}: {exc}", red))
        return False

    print(colorize(f"Exported {request.export_type} data to: {filepath}", green))
    return True
