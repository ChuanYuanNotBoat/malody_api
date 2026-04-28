# malody_api/core/services/player_service.py
import sqlite3
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import os
from ...core.database import get_db_connection, db_safe_operation
from ...core.models import Player
from ...utils.selector import MCSelector

class PlayerService:
    """玩家数据服务"""

    def _ranking_table(self, rank_type: str) -> str:
        return "player_rankings_mm" if rank_type == "mm" else "player_rankings"

    def _table_exists(self, cursor: sqlite3.Cursor, table_name: str) -> bool:
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
            (table_name,),
        )
        return cursor.fetchone() is not None

    def _load_manual_players(self, config_file: str = "players.txt") -> List[str]:
        if not os.path.exists(config_file):
            return []
        out: List[str] = []
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.isdigit():
                        out.append(line)
        except Exception:
            return []
        return out

    @db_safe_operation
    def get_mm_stats(self, mm_limit: int = 200) -> Dict[str, Any]:
        """
        MM/MMR 统计概览，供 API 与 stats CLI 复用。
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        def scalar(sql: str, params: tuple = ()) -> Any:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return row[0] if row else None

        def normalize_time(v: Any) -> Any:
            if isinstance(v, datetime):
                return v.isoformat()
            return v

        try:
            mm_limit = max(1, int(mm_limit or 200))

            counts: Dict[str, Optional[int]] = {}
            freshness: Dict[str, Any] = {}
            for table in ["player_rankings", "player_rankings_mm", "player_mmr_samples", "player_mmr_daily", "mm_crawl_status"]:
                if self._table_exists(cursor, table):
                    counts[table] = int(scalar(f"SELECT COUNT(*) FROM {table}") or 0)
                else:
                    counts[table] = None

            if self._table_exists(cursor, "player_rankings"):
                freshness["player_rankings_max_crawl_time"] = normalize_time(
                    scalar("SELECT MAX(crawl_time) FROM player_rankings")
                )
            if self._table_exists(cursor, "player_rankings_mm"):
                freshness["player_rankings_mm_max_crawl_time"] = normalize_time(
                    scalar("SELECT MAX(crawl_time) FROM player_rankings_mm")
                )
            if self._table_exists(cursor, "player_mmr_samples"):
                freshness["player_mmr_samples_max_crawl_time"] = normalize_time(
                    scalar("SELECT MAX(crawl_time) FROM player_mmr_samples")
                )
            if self._table_exists(cursor, "player_mmr_daily"):
                freshness["player_mmr_daily_day_min"] = scalar("SELECT MIN(day) FROM player_mmr_daily")
                freshness["player_mmr_daily_day_max"] = scalar("SELECT MAX(day) FROM player_mmr_daily")

            manual_players = set(self._load_manual_players())
            mm_top_players: set[str] = set()
            if self._table_exists(cursor, "player_rankings_mm"):
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
                mm_top_players = {str(row[0]) for row in cursor.fetchall() if row and row[0]}

            tracked = {
                "mm_limit": mm_limit,
                "manual_players_count": len(manual_players),
                "mm_top_players_count": len(mm_top_players),
                "union_players_count": len(manual_players | mm_top_players),
                "overlap_count": len(manual_players & mm_top_players),
                "manual_only_count": len(manual_players - mm_top_players),
                "mm_top_only_count": len(mm_top_players - manual_players),
                "manual_players": sorted(manual_players),
            }

            mm_snapshot: List[Dict[str, Any]] = []
            if self._table_exists(cursor, "player_rankings_mm"):
                cursor.execute(
                    """
                    WITH latest AS (
                        SELECT mode, MAX(crawl_time) AS ct
                        FROM player_rankings_mm
                        GROUP BY mode
                    )
                    SELECT r.mode,
                           r.crawl_time,
                           COUNT(*) AS rows_count,
                           COUNT(DISTINCT r.uid) AS uid_distinct,
                           COUNT(DISTINCT r.rank) AS rank_distinct,
                           MIN(r.rank) AS min_rank,
                           MAX(r.rank) AS max_rank,
                           SUM(CASE WHEN r.rank <= 0 THEN 1 ELSE 0 END) AS invalid_rank_rows
                    FROM player_rankings_mm r
                    JOIN latest l ON l.mode = r.mode AND l.ct = r.crawl_time
                    GROUP BY r.mode, r.crawl_time
                    ORDER BY r.mode
                    """
                )
                for row in cursor.fetchall():
                    rows_count = int(row[2] or 0)
                    uid_distinct = int(row[3] or 0)
                    rank_distinct = int(row[4] or 0)
                    mm_snapshot.append(
                        {
                            "mode": row[0],
                            "crawl_time": normalize_time(row[1]),
                            "rows": rows_count,
                            "uid_distinct": uid_distinct,
                            "rank_distinct": rank_distinct,
                            "dup_uid": max(rows_count - uid_distinct, 0),
                            "dup_rank": max(rows_count - rank_distinct, 0),
                            "min_rank": row[5],
                            "max_rank": row[6],
                            "invalid_rank_rows": int(row[7] or 0),
                        }
                    )

            mmr_sources: List[Dict[str, Any]] = []
            if self._table_exists(cursor, "player_mmr_samples"):
                cursor.execute(
                    """
                    SELECT source, COUNT(*) AS sample_count, COUNT(DISTINCT uid) AS player_count
                    FROM player_mmr_samples
                    GROUP BY source
                    ORDER BY sample_count DESC
                    """
                )
                mmr_sources = [
                    {
                        "source": row[0],
                        "sample_count": int(row[1] or 0),
                        "player_count": int(row[2] or 0),
                    }
                    for row in cursor.fetchall()
                ]

            mmr_daily_modes: List[Dict[str, Any]] = []
            if self._table_exists(cursor, "player_mmr_daily"):
                cursor.execute(
                    """
                    SELECT mode,
                           COUNT(*) AS rows_count,
                           COUNT(DISTINCT uid) AS player_count,
                           MIN(day) AS min_day,
                           MAX(day) AS max_day
                    FROM player_mmr_daily
                    GROUP BY mode
                    ORDER BY mode
                    """
                )
                mmr_daily_modes = [
                    {
                        "mode": row[0],
                        "rows": int(row[1] or 0),
                        "players": int(row[2] or 0),
                        "min_day": row[3],
                        "max_day": row[4],
                    }
                    for row in cursor.fetchall()
                ]

            crawl_status: List[Dict[str, Any]] = []
            if self._table_exists(cursor, "mm_crawl_status"):
                cursor.execute(
                    """
                    SELECT task, last_crawled, last_success, crawl_count, success_count, last_error
                    FROM mm_crawl_status
                    ORDER BY task
                    """
                )
                crawl_status = [
                    {
                        "task": row[0],
                        "last_crawled": normalize_time(row[1]),
                        "last_success": normalize_time(row[2]),
                        "crawl_count": int(row[3] or 0),
                        "success_count": int(row[4] or 0),
                        "fail_count": max(int(row[3] or 0) - int(row[4] or 0), 0),
                        "last_error": row[5],
                    }
                    for row in cursor.fetchall()
                ]

            return {
                "counts": counts,
                "freshness": freshness,
                "tracked_players": tracked,
                "mm_latest_snapshot_by_mode": mm_snapshot,
                "mmr_samples_by_source": mmr_sources,
                "mmr_daily_by_mode": mmr_daily_modes,
                "mm_crawl_status": crawl_status,
                "generated_at": datetime.now().isoformat(),
            }
        finally:
            conn.close()

    @db_safe_operation
    def get_top_players(self, selector: MCSelector, limit: int = 10, rank_type: str = "exp") -> List[Player]:
        """获取顶级玩家排名"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            where_clause, params = selector.build_player_sql_where("pr")
            table = self._ranking_table(rank_type)

            # 获取最新爬取时间
            latest_time = self._get_latest_crawl_time(cursor, selector, rank_type=rank_type)
            if not latest_time:
                return []

            # 添加时间条件（如果没有设置时间筛选）
            if not selector.filters['time_range']:
                if "crawl_time" not in where_clause:
                    where_clause += " AND pr.crawl_time = ?"
                    params.append(latest_time)

            if rank_type == "mm":
                query = f"""
                SELECT pr.rank, pr.name, pr.lv, pr.mm_value, pr.acc, pr.combo, pr.pc, pr.mode
                FROM {table} pr
                WHERE {where_clause}
                ORDER BY pr.rank
                LIMIT ?
                """
            else:
                query = f"""
                SELECT pr.rank, pr.name, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc, pr.mode
                FROM {table} pr
                WHERE {where_clause}
                ORDER BY pr.rank
                LIMIT ?
                """
            params.append(limit)

            cursor.execute(query, params)
            players_data = cursor.fetchall()

            result: List[Player] = []
            for row in players_data:
                payload = {
                    "rank": row[0],
                    "name": row[1],
                    "level": row[2],
                    "accuracy": row[4],
                    "combo": row[5],
                    "play_count": row[6],
                    "mode": row[7],
                    "rank_type": rank_type,
                }
                if rank_type == "mm":
                    payload["mm_value"] = row[3]
                else:
                    payload["exp"] = row[3]
                result.append(Player(**payload))
            return result

        finally:
            conn.close()

    def _get_latest_crawl_time(
        self,
        cursor: sqlite3.Cursor,
        selector: MCSelector,
        rank_type: str = "exp",
    ) -> Optional[datetime]:
        """获取最新爬取时间"""
        table = self._ranking_table(rank_type)
        try:
            if selector.filters['modes']:
                mode_condition = "pr.mode IN ({})".format(','.join(['?']*len(selector.filters['modes'])))
                cursor.execute(
                    f"SELECT MAX(crawl_time) FROM {table} pr WHERE {mode_condition}",
                    selector.filters['modes']
                )
            elif selector.current_mode != -1:
                cursor.execute(
                    f"SELECT MAX(crawl_time) FROM {table} WHERE mode = ?",
                    (selector.current_mode,)
                )
            else:
                cursor.execute(f"SELECT MAX(crawl_time) FROM {table}")

            result = cursor.fetchone()
            return result[0] if result and result[0] else None
        except Exception:
            return None
    
    @db_safe_operation
    def get_player_info(self, player_identifier: str, selector: MCSelector, rank_type: str = "exp") -> Dict[str, Any]:
        """获取玩家基本信息"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # 判断是UID还是名称，并获取player_id
            player_id = self._get_player_id(cursor, player_identifier)
            if not player_id:
                return {"error": f"未找到玩家: {player_identifier}"}
            table = self._ranking_table(rank_type)

            # 构建查询条件
            where_conditions = ["pr.player_id = ?"]
            query_params = [player_id]

            if selector.filters['modes']:
                where_conditions.append("pr.mode IN ({})".format(','.join(['?']*len(selector.filters['modes']))))
                query_params.extend(selector.filters['modes'])
            elif selector.current_mode != -1:
                where_conditions.append("pr.mode = ?")
                query_params.append(selector.current_mode)

            # 时间筛选
            if selector.filters['time_range']:
                where_conditions.append("pr.crawl_time BETWEEN ? AND ?")
                query_params.extend([
                    selector.filters['time_range']['start'],
                    selector.filters['time_range']['end']
                ])
            else:
                # 如果没有时间筛选，获取最新数据
                where_conditions.append(
                    f"pr.crawl_time = (SELECT MAX(crawl_time) FROM {table} WHERE player_id = ? AND mode = pr.mode)"
                )
                query_params.append(player_id)

            where_clause = " AND ".join(where_conditions)

            if rank_type == "mm":
                cursor.execute(
                    f"""
                    SELECT pr.rank, pr.lv, pr.mm_value, pr.acc, pr.combo, pr.pc, pr.mode, pr.crawl_time
                    FROM {table} pr
                    WHERE {where_clause}
                    ORDER BY pr.crawl_time DESC
                    LIMIT 1
                    """,
                    query_params
                )
            else:
                cursor.execute(
                    f"""
                    SELECT pr.rank, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc, pr.mode, pr.crawl_time
                    FROM {table} pr
                    WHERE {where_clause}
                    ORDER BY pr.crawl_time DESC
                    LIMIT 1
                    """,
                    query_params
                )

            player_data = cursor.fetchone()
            if not player_data:
                return {"error": "没有找到玩家数据"}

            # 获取玩家别名
            aliases = self._get_player_aliases(cursor, player_id)

            result = {
                "rank": player_data[0],
                "level": player_data[1],
                "accuracy": player_data[3],
                "combo": player_data[4],
                "play_count": player_data[5],
                "mode": player_data[6],
                "last_updated": player_data[7],
                "aliases": aliases,
                "rank_type": rank_type,
            }
            if rank_type == "mm":
                result["mm_value"] = player_data[2]
            else:
                result["exp"] = player_data[2]
                # 默认个人页返回中附带同模式 MM 快照，避免调用方额外筛选/再次请求
                if self._table_exists(cursor, "player_rankings_mm"):
                    mm_where = ["player_id = ?", "mode = ?"]
                    mm_params: List[Any] = [player_id, player_data[6]]
                    if selector.filters['time_range']:
                        mm_where.append("crawl_time BETWEEN ? AND ?")
                        mm_params.extend(
                            [
                                selector.filters['time_range']['start'],
                                selector.filters['time_range']['end'],
                            ]
                        )
                    mm_where_clause = " AND ".join(mm_where)
                    cursor.execute(
                        f"""
                        SELECT rank, mm_value, crawl_time
                        FROM player_rankings_mm
                        WHERE {mm_where_clause}
                        ORDER BY crawl_time DESC
                        LIMIT 1
                        """,
                        mm_params,
                    )
                    mm_row = cursor.fetchone()
                    if mm_row:
                        result["mm_snapshot"] = {
                            "rank": mm_row[0],
                            "mm_value": mm_row[1],
                            "last_updated": mm_row[2],
                        }
            return result

        finally:
            conn.close()
    
    @db_safe_operation
    def get_player_profile(self, identifier: str) -> Dict[str, Any]:
        """获取玩家详细资料（头像、头衔、成就、个人信息）"""
        conn = get_db_connection()
        cursor = conn.cursor()

        player_id = None
        uid = None

        # 获取 player_id 和 uid
        if identifier.isdigit():
            uid = identifier
            cursor.execute("SELECT player_id FROM player_identity WHERE uid = ?", (uid,))
            row = cursor.fetchone()
            if row:
                player_id = row[0]
        else:
            cursor.execute("SELECT player_id FROM player_aliases WHERE alias = ?", (identifier,))
            row = cursor.fetchone()
            if row:
                player_id = row[0]
                cursor.execute("SELECT uid FROM player_identity WHERE player_id = ?", (player_id,))
                uid_row = cursor.fetchone()
                if uid_row:
                    uid = uid_row[0]

        if not player_id and not uid:
            conn.close()
            return {"error": f"未找到玩家: {identifier}"}

        profile = {}
        if uid:
            cursor.execute("SELECT * FROM player_profiles WHERE uid = ?", (uid,))
            row = cursor.fetchone()
            if row:
                cols = [desc[0] for desc in cursor.description]
                profile = dict(zip(cols, row))

        titles = []
        if uid:
            cursor.execute("SELECT title FROM player_titles WHERE uid = ?", (uid,))
            titles = [r[0] for r in cursor.fetchall()]

        achievements = []
        if uid:
            cursor.execute("SELECT achievement_code FROM player_achievements WHERE uid = ?", (uid,))
            achievements = [r[0] for r in cursor.fetchall()]

        conn.close()
        return {
            "profile": profile,
            "titles": titles,
            "achievements": achievements
        }
    
    def _get_player_id(self, cursor: sqlite3.Cursor, identifier: str) -> Optional[int]:
        """获取玩家ID"""
        if identifier.isdigit():
            cursor.execute(
                "SELECT player_id FROM player_identity WHERE uid = ?", 
                (identifier,)
            )
        else:
            cursor.execute(
                "SELECT player_id FROM player_aliases WHERE alias = ?",
                (identifier,)
            )
        
        result = cursor.fetchone()
        return result[0] if result else None
    
    def _get_player_aliases(self, cursor: sqlite3.Cursor, player_id: int) -> List[str]:
        """获取玩家别名"""
        cursor.execute(
            "SELECT alias FROM player_aliases WHERE player_id = ? ORDER BY last_seen DESC",
            (player_id,)
        )
        return [row[0] for row in cursor.fetchall()]
    
    @db_safe_operation
    def get_player_history(
        self,
        player_name: str,
        selector: MCSelector,
        days: int = 30,
        metric: str = "exp_rank",
    ) -> List[Dict[str, Any]]:
        """获取玩家历史排名/MMR"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # 获取玩家ID
            player_id = self._get_player_id(cursor, player_name)
            if not player_id:
                return []

            # 计算时间范围
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            if metric == "mmr":
                uid = None
                if player_name.isdigit():
                    uid = player_name
                else:
                    cursor.execute("SELECT uid FROM player_identity WHERE player_id = ?", (player_id,))
                    uid_row = cursor.fetchone()
                    uid = uid_row[0] if uid_row and uid_row[0] else None
                if not uid:
                    return []

                query = """
                    SELECT day, mode, mmr, mm_rank, sample_time
                    FROM player_mmr_daily
                    WHERE uid = ? AND day >= ?
                """
                params: List[Any] = [uid, start_date.date().isoformat()]
                if selector.current_mode != -1:
                    query += " AND mode = ?"
                    params.append(selector.current_mode)
                query += " ORDER BY day, mode"
                cursor.execute(query, params)
                return [
                    {
                        "date": row[0],
                        "mode": row[1],
                        "mmr": row[2],
                        "mm_rank": row[3],
                        "sample_time": row[4],
                    }
                    for row in cursor.fetchall()
                ]

            table = "player_rankings_mm" if metric == "mm_rank" else "player_rankings"
            value_field = "mm_value" if metric == "mm_rank" else "exp"
            where_conditions = ["pr.player_id = ?", "pr.crawl_time >= ?"]
            query_params: List[Any] = [player_id, start_date]
            if selector.current_mode != -1:
                where_conditions.append("pr.mode = ?")
                query_params.append(selector.current_mode)
            where_clause = " AND ".join(where_conditions)

            cursor.execute(
                f"""
                SELECT pr.rank, pr.crawl_time, pr.mode, pr.{value_field}
                FROM {table} pr
                WHERE {where_clause}
                ORDER BY pr.crawl_time
                """,
                query_params
            )
            history_data = cursor.fetchall()
            return [
                {
                    "date": row[1],
                    "rank": row[0],
                    "mode": row[2],
                    value_field: row[3],
                }
                for row in history_data
            ]

        finally:
            conn.close()
    
    @db_safe_operation
    def search_players(self, keyword: str, selector: MCSelector, limit: int = 10) -> List[Dict[str, Any]]:
        """搜索玩家"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # 构建基础查询条件
            where_conditions = []
            params = []
            
            # 玩家名搜索
            where_conditions.append("pr.name LIKE ?")
            params.append(f"%{keyword}%")
            
            # 模式筛选
            if selector.filters['modes']:
                where_conditions.append("pr.mode IN ({})".format(','.join(['?']*len(selector.filters['modes']))))
                params.extend(selector.filters['modes'])
            elif selector.current_mode != -1:
                where_conditions.append("pr.mode = ?")
                params.append(selector.current_mode)
            
            # 获取最新数据
            latest_time = self._get_latest_crawl_time(cursor, selector)
            if latest_time:
                where_conditions.append("pr.crawl_time = ?")
                params.append(latest_time)
            
            where_clause = " AND ".join(where_conditions)
            
            query = f"""
            SELECT DISTINCT pr.name, pr.rank, pr.lv, pr.acc, pr.mode
            FROM player_rankings pr
            WHERE {where_clause}
            ORDER BY pr.rank
            LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            return [
                {
                    "name": row[0],
                    "rank": row[1],
                    "level": row[2],
                    "accuracy": row[3],
                    "mode": row[4]
                } for row in results
            ]
            
        finally:
            conn.close()
