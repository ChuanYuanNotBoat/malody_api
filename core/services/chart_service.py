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
            
            # 状态分布 - 确保所有状态都统计
            cursor.execute(f"SELECT c.status, COUNT(*) FROM charts c WHERE {where_clause} GROUP BY c.status", params)
            status_results = cursor.fetchall()
            status_dist = {0: 0, 1: 0, 2: 0}  # 初始化所有状态
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
                status_distribution={str(k): v for k, v in status_dist.items()},  # 转换为字符串键
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
            
            # 验证排序字段
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
            # 添加时间筛选
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
            # 创建临时选择器，强制设置状态为Stable(2)
            temp_selector = MCSelector()
            temp_selector.current_mode = selector.current_mode
            temp_selector.set_filters(
                players=selector.filters['players'],
                difficulties=selector.filters['difficulties'],
                time_range=selector.filters['time_range'],
                modes=selector.filters['modes'],
                statuses=[2]  # 只统计Stable谱面
            )
            
            where_clause, params = temp_selector.build_chart_sql_where("c")
            
            # 添加creator_name不为空的条件
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