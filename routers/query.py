# malody_api/routers/query.py
from fastapi import APIRouter, Query, HTTPException, Body
from typing import List, Dict, Any, Optional
from datetime import datetime
import json

# 修复导入路径 - 改为绝对导入
from malody_api.utils.query_builder import AdvancedQueryService
from malody_api.core.models import APIResponse

router = APIRouter(prefix="/query", tags=["advanced-query"])
query_service = AdvancedQueryService()

@router.post("/execute", response_model=APIResponse)
async def execute_advanced_query(
    table: str = Query(..., description="要查询的表名"),
    columns: Optional[List[str]] = Query(None, description="要查询的列，默认为所有列"),
    filters: Optional[List[Dict]] = Body(None, description="过滤条件列表"),
    order_by: Optional[List[str]] = Query(None, description="排序字段"),
    group_by: Optional[List[str]] = Query(None, description="分组字段"),
    having: Optional[List[Dict]] = Body(None, description="HAVING条件"),
    limit: int = Query(100, description="返回记录数限制", ge=1, le=1000),
    offset: int = Query(0, description="偏移量", ge=0),
    distinct: bool = Query(False, description="是否去重")
):
    """
    执行高级查询
    
    过滤条件示例:
    ```json
    [
      {"field": "mode", "operator": "=", "value": 0},
      {"field": "rank", "operator": "<=", "value": 100}
    ]
    ```
    
    支持的操作符: =, !=, >, <, >=, <=, LIKE, IN, BETWEEN, IS NULL, IS NOT NULL
    """
    try:
        result = query_service.execute_safe_query(
            table=table,
            columns=columns,
            filters=filters,
            order_by=order_by,
            group_by=group_by,
            having=having,
            limit=limit,
            offset=offset,
            distinct=distinct
        )
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return APIResponse(
            success=True,
            data=result["data"],
            message=f"查询成功，返回 {len(result['data'])} 条记录",
            timestamp=datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )

@router.get("/tables/{table_name}/schema", response_model=APIResponse)
async def get_table_schema(table_name: str):
    """获取表结构信息"""
    try:
        schema = query_service.get_table_schema(table_name)
        
        if "error" in schema:
            raise HTTPException(status_code=404, detail=schema["error"])
        
        return APIResponse(
            success=True,
            data=schema,
            timestamp=datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )

@router.get("/database/stats", response_model=APIResponse)
async def get_database_statistics():
    """获取数据库统计信息"""
    try:
        stats = query_service.get_database_stats()
        
        if "error" in stats:
            raise HTTPException(status_code=500, detail=stats["error"])
        
        return APIResponse(
            success=True,
            data=stats,
            timestamp=datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )

@router.get("/predefined-queries", response_model=APIResponse)
async def get_predefined_queries():
    """获取预定义查询示例"""
    predefined_queries = {
        "top_players_by_mode": {
            "description": "获取各模式前10名玩家",
            "endpoint": "/query/execute",
            "method": "POST",
            "parameters": {
                "table": "player_rankings",
                "columns": ["mode", "rank", "name", "lv", "acc"],
                "filters": [
                    {"field": "rank", "operator": "<=", "value": 10}
                ],
                "order_by": ["mode", "rank"],
                "group_by": ["mode"],
                "limit": 100
            }
        },
        "chart_statistics_by_status": {
            "description": "按状态统计谱面信息",
            "endpoint": "/query/execute", 
            "method": "POST",
            "parameters": {
                "table": "charts",
                "columns": ["status", "COUNT(*) as count", "AVG(heat) as avg_heat"],
                "group_by": ["status"],
                "order_by": ["status"]
            }
        },
        "player_ranking_history": {
            "description": "获取玩家排名历史",
            "endpoint": "/query/execute",
            "method": "POST", 
            "parameters": {
                "table": "player_rankings",
                "columns": ["name", "rank", "crawl_time"],
                "filters": [
                    {"field": "name", "operator": "LIKE", "value": "Zani"}
                ],
                "order_by": ["crawl_time DESC"],
                "limit": 50
            }
        },
        "top_creators_by_stable_charts": {
            "description": "按Stable谱面数排序的创作者",
            "endpoint": "/query/execute",
            "method": "POST",
            "parameters": {
                "table": "charts",
                "columns": ["creator_name", "COUNT(*) as stable_count", "AVG(heat) as avg_heat"],
                "filters": [
                    {"field": "status", "operator": "=", "value": 2},
                    {"field": "creator_name", "operator": "IS NOT NULL", "value": None}
                ],
                "group_by": ["creator_name"],
                "order_by": ["stable_count DESC"],
                "limit": 20
            }
        }
    }
    
    return APIResponse(
        success=True,
        data=predefined_queries,
        message="预定义查询示例",
        timestamp=datetime.now()
    )