# malody_api/core/services/player_service.py
import sqlite3
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from ...core.database import get_db_connection, db_safe_operation
from ...core.models import Player, PlayerDetail, PlayerHistoryPoint, APIResponse
from ...utils.selector import MCSelector

class PlayerService:
    """玩家数据服务"""
    
    @db_safe_operation
    def get_top_players(self, selector: MCSelector, limit: int = 10) -> List[Player]:
        """获取顶级玩家排名"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            where_clause, params = selector.build_player_sql_where("pr")
            
            # 获取最新爬取时间
            latest_time = self._get_latest_crawl_time(cursor, selector)
            if not latest_time:
                return []
            
            # 添加时间条件（如果没有设置时间筛选）
            if not selector.filters['time_range']:
                if "crawl_time" not in where_clause:
                    where_clause += " AND pr.crawl_time = ?"
                    params.append(latest_time)
            
            query = f"""
            SELECT pr.rank, pr.name, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc, pr.mode
            FROM player_rankings pr
            WHERE {where_clause}
            ORDER BY pr.rank
            LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            players_data = cursor.fetchall()
            
            return [
                Player(
                    rank=row[0],
                    name=row[1],
                    level=row[2],
                    exp=row[3],
                    accuracy=row[4],
                    combo=row[5],
                    play_count=row[6],
                    mode=row[7]
                ) for row in players_data
            ]
            
        finally:
            conn.close()
    
    def _get_latest_crawl_time(self, cursor: sqlite3.Cursor, selector: MCSelector) -> Optional[datetime]:
        """获取最新爬取时间"""
        try:
            if selector.filters['modes']:
                mode_condition = "pr.mode IN ({})".format(','.join(['?']*len(selector.filters['modes'])))
                cursor.execute(
                    f"SELECT MAX(crawl_time) FROM player_rankings pr WHERE {mode_condition}",
                    selector.filters['modes']
                )
            elif selector.current_mode != -1:
                cursor.execute(
                    "SELECT MAX(crawl_time) FROM player_rankings WHERE mode = ?",
                    (selector.current_mode,)
                )
            else:
                cursor.execute("SELECT MAX(crawl_time) FROM player_rankings")
            
            result = cursor.fetchone()
            return result[0] if result and result[0] else None
        except Exception:
            return None
    
    @db_safe_operation
    def get_player_info(self, player_identifier: str, selector: MCSelector) -> Dict[str, Any]:
        """获取玩家详细信息"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # 判断是UID还是名称，并获取player_id
            player_id = self._get_player_id(cursor, player_identifier)
            if not player_id:
                return {"error": f"未找到玩家: {player_identifier}"}
            
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
                where_conditions.append("pr.crawl_time = (SELECT MAX(crawl_time) FROM player_rankings WHERE player_id = ? AND mode = pr.mode)")
                query_params.append(player_id)
            
            where_clause = " AND ".join(where_conditions)
            
            cursor.execute(
                f"""
                SELECT pr.rank, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc, pr.mode, pr.crawl_time
                FROM player_rankings pr
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
            
            return {
                "rank": player_data[0],
                "level": player_data[1],
                "exp": player_data[2],
                "accuracy": player_data[3],
                "combo": player_data[4],
                "play_count": player_data[5],
                "mode": player_data[6],
                "last_updated": player_data[7],
                "aliases": aliases
            }
            
        finally:
            conn.close()
    
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
    def get_player_history(self, player_name: str, selector: MCSelector, days: int = 30) -> List[PlayerHistoryPoint]:
        """获取玩家历史排名"""
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
            
            # 构建查询条件
            where_conditions = [
                "pr.player_id = ?", 
                "pr.mode = ?",
                "pr.crawl_time >= ?"
            ]
            query_params = [player_id, selector.current_mode, start_date]
            
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
            
            return [
                PlayerHistoryPoint(
                    date=row[1],
                    rank=row[0]
                ) for row in history_data
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