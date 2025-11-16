# malody_api/core/services/analysis_service.py
import sqlite3
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from ...core.database import get_db_connection, db_safe_operation
from ...utils.selector import MCSelector

class AnalysisService:
    """数据分析服务"""
    
    @db_safe_operation
    def analyze_player_trends(self, start_date: datetime, selector: MCSelector, 
                            display_fields: List[str] = None) -> Dict[str, Any]:
        """分析玩家数据变化趋势"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            if display_fields is None:
                display_fields = ["rank", "lv", "exp", "acc", "combo", "pc"]
            
            # 获取起始日期的数据
            cursor.execute(
                """
                SELECT crawl_time 
                FROM player_rankings 
                WHERE mode = ? AND DATE(crawl_time) >= DATE(?)
                ORDER BY crawl_time
                LIMIT 1
                """,
                (selector.current_mode, start_date)
            )
            
            start_result = cursor.fetchone()
            if not start_result:
                return {"error": f"在 {start_date.date()} 及之后没有找到数据"}
            
            start_crawl_time = start_result[0]
            
            # 获取最新数据
            cursor.execute(
                "SELECT MAX(crawl_time) FROM player_rankings WHERE mode = ?",
                (selector.current_mode,)
            )
            end_crawl_time = cursor.fetchone()[0]
            
            if not end_crawl_time:
                return {"error": "没有最新数据"}
            
            # 获取起始日期的玩家数据
            cursor.execute(
                """
                SELECT player_id, name, rank, lv, exp, acc, combo, pc
                FROM player_rankings
                WHERE mode = ? AND crawl_time = ?
                ORDER BY rank
                """,
                (selector.current_mode, start_crawl_time)
            )
            
            start_players = {row[0]: (row[1], row[2], row[3], row[4], row[5], row[6], row[7]) 
                           for row in cursor.fetchall()}
            
            # 获取最新日期的玩家数据
            cursor.execute(
                """
                SELECT player_id, name, rank, lv, exp, acc, combo, pc
                FROM player_rankings
                WHERE mode = ? AND crawl_time = ?
                ORDER BY rank
                """,
                (selector.current_mode, end_crawl_time)
            )
            
            end_players = {row[0]: (row[1], row[2], row[3], row[4], row[5], row[6], row[7]) 
                         for row in cursor.fetchall()}
            
            # 分析变化
            all_player_ids = set(start_players.keys()) | set(end_players.keys())
            trend_data = []
            
            for player_id in all_player_ids:
                in_start = player_id in start_players
                in_end = player_id in end_players
                
                if in_start and in_end:
                    # 一直在榜的玩家
                    start_name, start_rank, start_lv, start_exp, start_acc, start_combo, start_pc = start_players[player_id]
                    end_name, end_rank, end_lv, end_exp, end_acc, end_combo, end_pc = end_players[player_id]
                    
                    current_name = end_name if end_name != start_name else start_name
                    
                    player_trend = {
                        'player_id': player_id,
                        'name': current_name,
                        'status': '=',  # 一直在榜
                        'start_rank': start_rank,
                        'end_rank': end_rank,
                        'rank_change': end_rank - start_rank,
                        'start_lv': start_lv,
                        'end_lv': end_lv,
                        'lv_change': end_lv - start_lv,
                        'start_exp': start_exp,
                        'end_exp': end_exp,
                        'exp_change': end_exp - start_exp,
                        'start_acc': start_acc,
                        'end_acc': end_acc,
                        'acc_change': end_acc - start_acc,
                        'start_combo': start_combo,
                        'end_combo': end_combo,
                        'combo_change': end_combo - start_combo,
                        'start_pc': start_pc,
                        'end_pc': end_pc,
                        'pc_change': end_pc - start_pc
                    }
                    
                    # 检查是否有变化（基于用户选择的字段）
                    has_changes = False
                    for field in display_fields:
                        if field in ['rank', 'lv', 'exp', 'acc', 'combo', 'pc']:
                            change_field = f"{field}_change"
                            if player_trend.get(change_field, 0) != 0:
                                has_changes = True
                                break
                    
                    if has_changes:
                        trend_data.append(player_trend)
                        
                elif in_start and not in_end:
                    # 掉出榜的玩家
                    start_name, start_rank, start_lv, start_exp, start_acc, start_combo, start_pc = start_players[player_id]
                    
                    trend_data.append({
                        'player_id': player_id,
                        'name': start_name,
                        'status': '-',  # 掉出榜
                        'start_rank': start_rank,
                        'end_rank': None,
                        'start_lv': start_lv,
                        'end_lv': None,
                        'start_exp': start_exp,
                        'end_exp': None,
                        'start_acc': start_acc,
                        'end_acc': None,
                        'start_combo': start_combo,
                        'end_combo': None,
                        'start_pc': start_pc,
                        'end_pc': None
                    })
                    
                else:
                    # 新上榜的玩家
                    end_name, end_rank, end_lv, end_exp, end_acc, end_combo, end_pc = end_players[player_id]
                    
                    trend_data.append({
                        'player_id': player_id,
                        'name': end_name,
                        'status': '+',  # 新上榜
                        'start_rank': None,
                        'end_rank': end_rank,
                        'start_lv': None,
                        'end_lv': end_lv,
                        'start_exp': None,
                        'end_exp': end_exp,
                        'start_acc': None,
                        'end_acc': end_acc,
                        'start_combo': None,
                        'end_combo': end_combo,
                        'start_pc': None,
                        'end_pc': end_pc
                    })
            
            # 按结束排名排序
            trend_data.sort(key=lambda x: (x['end_rank'] is None, x['end_rank'] or 9999))
            
            # 统计信息
            stayed_players = len([p for p in trend_data if p['status'] == '='])
            dropped_players = len([p for p in trend_data if p['status'] == '-'])
            new_players = len([p for p in trend_data if p['status'] == '+'])
            
            return {
                "trend_data": trend_data,
                "summary": {
                    "total_players": len(trend_data),
                    "stayed_players": stayed_players,
                    "dropped_players": dropped_players,
                    "new_players": new_players,
                    "time_range": {
                        "start": start_crawl_time,
                        "end": end_crawl_time
                    }
                },
                "display_fields": display_fields
            }
            
        finally:
            conn.close()
    
    @db_safe_operation
    def get_chart_trends(self, selector: MCSelector, period: str = "months") -> List[Dict[str, Any]]:
        """获取谱面更新趋势"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # 构建基础查询条件（排除时间筛选）
            base_filters = selector.filters.copy()
            base_filters['time_range'] = None
            
            where_clause, params = selector.build_chart_sql_where("c")
            
            # 根据时间段设置分组
            if period == "days":
                time_condition = "c.last_updated >= date('now', '-30 days')"
                group_by = "DATE(c.last_updated)"
                order_by = "DATE(c.last_updated)"
            else:  # months
                time_condition = "c.last_updated >= date('now', '-1 year')"
                group_by = "strftime('%Y-%m', c.last_updated)"
                order_by = "strftime('%Y-%m', c.last_updated)"
            
            # 正确拼接时间条件
            if where_clause != "1=1":
                where_clause += f" AND {time_condition}"
            else:
                where_clause = time_condition
            
            query = f"""
            SELECT {group_by}, COUNT(*) 
            FROM charts c 
            WHERE {where_clause} 
            GROUP BY {group_by} 
            ORDER BY {order_by}
            """
            
            cursor.execute(query, params)
            trend_data = cursor.fetchall()
            
            return [
                {
                    "period": row[0],
                    "count": row[1]
                } for row in trend_data
            ]
            
        finally:
            conn.close()
    
    @db_safe_operation
    def compare_modes(self, modes: List[int]) -> List[Dict[str, Any]]:
        """比较不同模式的谱面数据"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            comparison_data = []
            
            for mode in modes:
                # 构建模式特定的选择器
                mode_selector = MCSelector()
                mode_selector.set_filters(modes=[mode])
                
                where_clause, params = mode_selector.build_chart_sql_where("c")
                
                # 总谱面数
                cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause}", params)
                total_charts = cursor.fetchone()[0] or 0
                
                # 创作者数
                cursor.execute(f"SELECT COUNT(DISTINCT c.creator_name) FROM charts c WHERE {where_clause} AND c.creator_name IS NOT NULL", params)
                unique_creators = cursor.fetchone()[0] or 0
                
                # 平均热度
                cursor.execute(f"SELECT AVG(c.heat) FROM charts c WHERE {where_clause} AND c.heat > 0", params)
                avg_heat = cursor.fetchone()[0] or 0
                
                # 平均难度
                cursor.execute(f"SELECT AVG(CAST(c.level AS REAL)) FROM charts c WHERE {where_clause} AND c.level IS NOT NULL AND c.level != '' AND CAST(c.level AS REAL) > 0", params)
                avg_level = cursor.fetchone()[0] or 0
                
                # Stable谱面数
                cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.status = 2", params)
                stable_charts = cursor.fetchone()[0] or 0
                
                mode_names = {0: "Key", 1: "Step", 2: "DJ", 3: "Catch", 4: "Pad", 
                            5: "Taiko", 6: "Ring", 7: "Slide", 8: "Live", 9: "Cube"}
                
                comparison_data.append({
                    "mode": mode,
                    "mode_name": mode_names.get(mode, "未知"),
                    "total_charts": total_charts,
                    "unique_creators": unique_creators,
                    "avg_heat": float(avg_heat),
                    "avg_level": float(avg_level),
                    "stable_charts": stable_charts,
                    "stability_rate": (stable_charts / total_charts * 100) if total_charts > 0 else 0
                })
            
            # 按总谱面数排序
            comparison_data.sort(key=lambda x: x["total_charts"], reverse=True)
            
            return comparison_data
            
        finally:
            conn.close()