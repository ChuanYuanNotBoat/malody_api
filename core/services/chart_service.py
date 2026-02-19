# malody_api/core/services/chart_service.py
import sqlite3
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from ...core.database import get_db_connection, db_safe_operation
from ...core.models import ChartStats, HotChart, CreatorStats
from ...utils.selector import MCSelector

class ChartService:
    """谱面数据服务"""
    
    @db_safe_operation
    def get_chart_stats(self, selector: MCSelector) -> ChartStats:
        """获取谱面统计信息"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            where_clause, params = selector.build_chart_sql_where("c")
            
            # 总谱面数
            cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause}", params)
            total_charts = cursor.fetchone()[0] or 0
            
            # 唯一歌曲数
            cursor.execute(f"SELECT COUNT(DISTINCT c.sid) FROM charts c WHERE {where_clause}", params)
            unique_songs = cursor.fetchone()[0] or 0
            
            # 创作者数
            cursor.execute(f"SELECT COUNT(DISTINCT c.creator_name) FROM charts c WHERE {where_clause} AND c.creator_name IS NOT NULL", params)
            unique_creators = cursor.fetchone()[0] or 0
            
            # 状态分布
            cursor.execute(f"SELECT c.status, COUNT(*) FROM charts c WHERE {where_clause} GROUP BY c.status", params)
            status_results = cursor.fetchall()
            status_dist = {0: 0, 1: 0, 2: 0}
            for status, count in status_results:
                if status in [0, 1, 2]:
                    status_dist[status] = count
            
            # 难度分布
            cursor.execute(
                f"SELECT c.level, COUNT(*) FROM charts c WHERE {where_clause} AND c.level IS NOT NULL AND c.level != '' GROUP BY c.level ORDER BY CAST(c.level AS REAL)",
                params
            )
            level_results = cursor.fetchall()
            level_dist = {str(level): count for level, count in level_results}
            
            # 热度统计
            cursor.execute(f"SELECT AVG(c.heat), MAX(c.heat), MIN(c.heat) FROM charts c WHERE {where_clause} AND c.heat > 0", params)
            heat_stats_result = cursor.fetchone()
            heat_avg, heat_max, heat_min = heat_stats_result or (0, 0, 0)
            
            return ChartStats(
                total_charts=total_charts,
                unique_songs=unique_songs,
                unique_creators=unique_creators,
                status_distribution={str(k): v for k, v in status_dist.items()},
                level_distribution=level_dist,
                heat_stats={
                    "average": float(heat_avg or 0),
                    "max": float(heat_max or 0),
                    "min": float(heat_min or 0)
                }
            )
            
        finally:
            conn.close()
    
    @db_safe_operation
    def get_hot_charts(self, selector: MCSelector, sort_field: str = "heat", limit: int = 10) -> List[HotChart]:
        """获取热门谱面"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            where_clause, params = selector.build_chart_sql_where("c")
            
            valid_sort_fields = ["heat", "donate_count", "play_count", "love_count"]
            if sort_field not in valid_sort_fields:
                sort_field = "heat"
            
            query = f"""
            SELECT c.cid, s.title, s.artist, c.version, c.level, c.status, 
                   c.creator_name, c.heat, c.donate_count
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE {where_clause}
            ORDER BY c.{sort_field} DESC
            LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            return [
                HotChart(
                    cid=row[0],
                    title=row[1],
                    artist=row[2],
                    version=row[3],
                    level=row[4],
                    status=row[5],
                    creator_name=row[6],
                    heat=row[7],
                    donate_count=row[8]
                ) for row in results
            ]
            
        finally:
            conn.close()
    
    @db_safe_operation
    def get_recent_charts(self, selector: MCSelector, days: int = 7, limit: int = 10) -> List[HotChart]:
        """获取最近更新的谱面"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            where_clause, params = selector.build_chart_sql_where("c")
            if where_clause != "1=1":
                where_clause += " AND c.last_updated >= ?"
            else:
                where_clause = "c.last_updated >= ?"
            params.append(start_date)
            
            query = f"""
            SELECT c.cid, s.title, s.artist, c.version, c.level, c.status, 
                   c.creator_name, c.heat, c.donate_count, c.last_updated
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE {where_clause}
            ORDER BY c.last_updated DESC
            LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            return [
                HotChart(
                    cid=row[0],
                    title=row[1],
                    artist=row[2],
                    version=row[3],
                    level=row[4],
                    status=row[5],
                    creator_name=row[6],
                    heat=row[7],
                    donate_count=row[8]
                ) for row in results
            ]
            
        finally:
            conn.close()
    
    @db_safe_operation
    def get_stable_creators(self, selector: MCSelector, limit: int = 20) -> List[CreatorStats]:
        """获取Stable谱面创作者排行榜"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            temp_selector = MCSelector()
            temp_selector.current_mode = selector.current_mode
            temp_selector.set_filters(
                players=selector.filters['players'],
                difficulties=selector.filters['difficulties'],
                time_range=selector.filters['time_range'],
                modes=selector.filters['modes'],
                statuses=[2]
            )
            
            where_clause, params = temp_selector.build_chart_sql_where("c")
            
            if where_clause != "1=1":
                where_clause += " AND c.creator_name IS NOT NULL"
            else:
                where_clause = "c.creator_name IS NOT NULL"
            
            query = f"""
            SELECT c.creator_name, COUNT(*) as stable_count,
                AVG(CAST(c.level AS REAL)) as avg_level,
                AVG(c.heat) as avg_heat,
                MAX(c.heat) as max_heat
            FROM charts c
            WHERE {where_clause}
            GROUP BY c.creator_name
            ORDER BY stable_count DESC, avg_heat DESC
            LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            return [
                CreatorStats(
                    creator_name=row[0],
                    stable_count=row[1],
                    avg_level=float(row[2]) if row[2] else None,
                    avg_heat=float(row[3]) if row[3] else None,
                    max_heat=row[4]
                ) for row in results
            ]
            
        finally:
            conn.close()
    
    @db_safe_operation
    def get_chart_detail(self, cid: int) -> Dict[str, Any]:
        """获取单个谱面的详细信息"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.*, s.title, s.artist, s.bpm, s.length, s.cover_url
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE c.cid = ?
        """, (cid,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {"error": f"谱面不存在: {cid}"}
        cols = [desc[0] for desc in cursor.description]
        data = dict(zip(cols, row))
        conn.close()
        return data
    
    @db_safe_operation
    def get_stabilizer_stats(self, player_name: str) -> Dict[str, Any]:
        """获取稳定者的统计信息"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as total,
                   COUNT(DISTINCT mode) as modes,
                   AVG(heat) as avg_heat,
                   AVG(CAST(level AS REAL)) as avg_level
            FROM charts
            WHERE stabled_by_name LIKE ? AND status = 2
        """, (f"%{player_name}%",))
        stats = cursor.fetchone()
        conn.close()
        return {
            "total": stats[0],
            "modes": stats[1],
            "avg_heat": float(stats[2]) if stats[2] else 0,
            "avg_level": float(stats[3]) if stats[3] else 0
        }
    
    @db_safe_operation
    def get_stabilizer_charts(self, player_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        """获取稳定者审核的谱面列表"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.cid, s.title, s.artist, c.version, c.level, c.mode, c.status,
                   c.heat, c.donate_count, c.play_count, c.last_updated
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE c.stabled_by_name LIKE ? AND c.status = 2
            ORDER BY c.last_updated DESC
            LIMIT ?
        """, (f"%{player_name}%", limit))
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        result = [dict(zip(cols, row)) for row in rows]
        conn.close()
        return result
    
    @db_safe_operation
    def search_charts(self, keyword: str, selector: MCSelector, limit: int = 10) -> List[Dict[str, Any]]:
        """搜索谱面"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            where_clause, params = selector.build_chart_sql_where("c")
            where_clause += " AND (s.title LIKE ? OR s.artist LIKE ?)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])
            
            query = f"""
            SELECT c.cid, s.title, s.artist, c.version, c.level, c.status, 
                   c.creator_name, c.heat, c.donate_count
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE {where_clause}
            ORDER BY c.heat DESC
            LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            return [
                {
                    "cid": row[0],
                    "title": row[1],
                    "artist": row[2],
                    "version": row[3],
                    "level": row[4],
                    "status": row[5],
                    "creator_name": row[6],
                    "heat": row[7],
                    "donate_count": row[8]
                } for row in results
            ]
            
        finally:
            conn.close()
    
    @db_safe_operation
    def search_creators(self, keyword: str, selector: MCSelector, limit: int = 10) -> List[Dict[str, Any]]:
        """搜索创作者"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            where_clause, params = selector.build_chart_sql_where("c")
            where_clause += " AND c.creator_name LIKE ?"
            params.append(f"%{keyword}%")
            
            query = f"""
            SELECT c.creator_name, COUNT(*) as chart_count, 
                   AVG(c.heat) as avg_heat, MAX(c.heat) as max_heat
            FROM charts c
            WHERE {where_clause}
            GROUP BY c.creator_name
            ORDER BY chart_count DESC
            LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            return [
                {
                    "creator_name": row[0],
                    "chart_count": row[1],
                    "avg_heat": float(row[2]) if row[2] else 0,
                    "max_heat": row[3]
                } for row in results
            ]
            
        finally:
            conn.close()