# malody_api/utils/query_builder.py
import sqlite3
from typing import List, Dict, Any, Optional, Union, Tuple
import re

class SafeQueryBuilder:
    """安全的SQL查询构建器，防止SQL注入"""
    
    # 允许的表名白名单
    ALLOWED_TABLES = {
        'player_rankings', 'player_identity', 'player_aliases', 
        'charts', 'songs', 'player_config', 'player_crawl_status',
        'import_metadata', 'stb_crawler_state'
    }
    
    # 允许的聚合函数
    ALLOWED_AGGREGATES = {'COUNT', 'SUM', 'AVG', 'MAX', 'MIN', 'GROUP_CONCAT'}
    
    @staticmethod
    def validate_table_name(table: str) -> bool:
        """验证表名是否安全"""
        return table in SafeQueryBuilder.ALLOWED_TABLES
    
    @staticmethod
    def validate_column_name(column: str) -> bool:
        """验证列名是否安全"""
        # 只允许字母、数字、下划线
        return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', column))
    
    @staticmethod
    def build_select_query(
        table: str,
        columns: List[str] = None,
        where_conditions: List[str] = None,
        order_by: List[str] = None,
        group_by: List[str] = None,
        having_conditions: List[str] = None,
        limit: int = None,
        offset: int = None,
        distinct: bool = False
    ) -> Tuple[str, List[Any]]:
        """
        构建安全的SELECT查询
        
        返回: (sql_query, parameters)
        """
        # 验证表名
        if not SafeQueryBuilder.validate_table_name(table):
            raise ValueError(f"不允许查询表: {table}")
        
        params = []
        
        # SELECT 部分
        if columns:
            # 验证列名
            for col in columns:
                if not SafeQueryBuilder.validate_column_name(col.split('(')[0].split(' ')[0]):
                    raise ValueError(f"无效的列名: {col}")
            select_clause = ", ".join(columns)
        else:
            select_clause = "*"
        
        # DISTINCT
        distinct_clause = "DISTINCT " if distinct else ""
        
        # FROM 部分
        from_clause = f"FROM {table}"
        
        # WHERE 部分
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)
        
        # GROUP BY 部分
        group_by_clause = ""
        if group_by:
            # 验证分组列
            for col in group_by:
                if not SafeQueryBuilder.validate_column_name(col):
                    raise ValueError(f"无效的分组列: {col}")
            group_by_clause = "GROUP BY " + ", ".join(group_by)
        
        # HAVING 部分
        having_clause = ""
        if having_conditions:
            having_clause = "HAVING " + " AND ".join(having_conditions)
        
        # ORDER BY 部分
        order_by_clause = ""
        if order_by:
            # 验证排序列
            for col in order_by:
                base_col = col.replace(' DESC', '').replace(' ASC', '').strip()
                if not SafeQueryBuilder.validate_column_name(base_col):
                    raise ValueError(f"无效的排序列: {col}")
            order_by_clause = "ORDER BY " + ", ".join(order_by)
        
        # LIMIT 和 OFFSET
        limit_clause = ""
        if limit is not None:
            if not isinstance(limit, int) or limit < 0:
                raise ValueError("LIMIT必须是正整数")
            limit_clause = f"LIMIT {limit}"
            if offset is not None:
                if not isinstance(offset, int) or offset < 0:
                    raise ValueError("OFFSET必须是正整数")
                limit_clause += f" OFFSET {offset}"
        
        # 构建完整查询
        query_parts = [
            f"SELECT {distinct_clause}{select_clause}",
            from_clause,
            where_clause,
            group_by_clause,
            having_clause,
            order_by_clause,
            limit_clause
        ]
        
        sql = " ".join(part for part in query_parts if part)
        return sql, params
    
    @staticmethod
    def parse_filter_condition(field: str, operator: str, value: Any) -> Tuple[str, List[Any]]:
        """
        解析过滤条件为安全的SQL片段
        
        支持的操作符: =, !=, >, <, >=, <=, LIKE, IN, BETWEEN, IS NULL, IS NOT NULL
        """
        if not SafeQueryBuilder.validate_column_name(field):
            raise ValueError(f"无效的字段名: {field}")
        
        operators = {'=', '!=', '>', '<', '>=', '<=', 'LIKE', 'IN', 'BETWEEN', 'IS NULL', 'IS NOT NULL'}
        if operator.upper() not in operators:
            raise ValueError(f"不支持的操作符: {operator}")
        
        operator = operator.upper()
        
        if operator in ['IS NULL', 'IS NOT NULL']:
            return f"{field} {operator}", []
        
        elif operator == 'IN':
            if not isinstance(value, (list, tuple)):
                raise ValueError("IN操作符的值必须是列表或元组")
            placeholders = ', '.join(['?' for _ in value])
            return f"{field} IN ({placeholders})", list(value)
        
        elif operator == 'BETWEEN':
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValueError("BETWEEN操作符的值必须是包含2个元素的列表或元组")
            return f"{field} BETWEEN ? AND ?", list(value)
        
        else:
            return f"{field} {operator} ?", [value]

class AdvancedQueryService:
    """高级查询服务"""
    
    def __init__(self):
        from ..core.database import get_db_connection
        self.get_connection = get_db_connection
    
    def execute_safe_query(
        self,
        table: str,
        columns: List[str] = None,
        filters: List[Dict] = None,
        order_by: List[str] = None,
        group_by: List[str] = None,
        having: List[Dict] = None,
        limit: int = 100,
        offset: int = 0,
        distinct: bool = False
    ) -> Dict[str, Any]:
        """
        执行安全的自定义查询
        
        filters示例: [{"field": "mode", "operator": "=", "value": 0}]
        having示例: [{"field": "count", "operator": ">", "value": 10}]
        """
        try:
            # 构建WHERE条件
            where_conditions = []
            where_params = []
            if filters:
                for filter_obj in filters:
                    condition, params = SafeQueryBuilder.parse_filter_condition(
                        filter_obj['field'], 
                        filter_obj['operator'], 
                        filter_obj['value']
                    )
                    where_conditions.append(condition)
                    where_params.extend(params)
            
            # 构建HAVING条件
            having_conditions = []
            having_params = []
            if having:
                for having_obj in having:
                    condition, params = SafeQueryBuilder.parse_filter_condition(
                        having_obj['field'], 
                        having_obj['operator'], 
                        having_obj['value']
                    )
                    having_conditions.append(condition)
                    having_params.extend(params)
            
            # 构建完整查询
            sql, build_params = SafeQueryBuilder.build_select_query(
                table=table,
                columns=columns,
                where_conditions=where_conditions,
                order_by=order_by,
                group_by=group_by,
                having_conditions=having_conditions,
                limit=limit,
                offset=offset,
                distinct=distinct
            )
            
            # 合并参数
            all_params = where_params + having_params + build_params
            
            # 执行查询
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(sql, all_params)
            results = cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            
            conn.close()
            
            # 转换为字典列表
            data = []
            for row in results:
                data.append(dict(zip(columns, row)))
            
            return {
                "success": True,
                "data": data,
                "query": sql,
                "params": all_params,
                "total_count": len(data)
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "query": "",
                "params": []
            }
    
    def get_table_schema(self, table_name: str) -> Dict[str, Any]:
        """获取表结构信息"""
        if not SafeQueryBuilder.validate_table_name(table_name):
            return {"error": f"不允许查询表: {table_name}"}
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # 获取列信息
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            
            # 获取索引信息
            cursor.execute(f"PRAGMA index_list({table_name})")
            indexes = cursor.fetchall()
            
            # 获取外键信息
            cursor.execute(f"PRAGMA foreign_key_list({table_name})")
            foreign_keys = cursor.fetchall()
            
            conn.close()
            
            column_info = []
            for col in columns:
                column_info.append({
                    "cid": col[0],
                    "name": col[1],
                    "type": col[2],
                    "notnull": bool(col[3]),
                    "default_value": col[4],
                    "pk": bool(col[5])
                })
            
            return {
                "table_name": table_name,
                "columns": column_info,
                "index_count": len(indexes),
                "foreign_key_count": len(foreign_keys)
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def get_database_stats(self) -> Dict[str, Any]:
        """获取数据库统计信息"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # 获取所有表的信息
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            table_stats = {}
            total_records = 0
            
            for table in tables:
                if SafeQueryBuilder.validate_table_name(table):
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    table_stats[table] = count
                    total_records += count
            
            # 获取数据库大小
            cursor.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
            db_size = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                "total_tables": len(tables),
                "total_records": total_records,
                "table_stats": table_stats,
                "database_size_bytes": db_size,
                "database_size_mb": round(db_size / (1024 * 1024), 2)
            }
            
        except Exception as e:
            return {"error": str(e)}