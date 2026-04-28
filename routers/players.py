# malody_api/routers/players.py
from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional, Literal
from datetime import datetime, timedelta
import re

# 改为绝对导入
from malody_api.core.services import PlayerService
from malody_api.utils.selector import MCSelector
from malody_api.core.models import APIResponse, Player, PlayerDetail, PlayerHistoryPoint

router = APIRouter(prefix="/players", tags=["players"])
player_service = PlayerService()

def create_selector_from_query(
    players: Optional[str] = None,
    modes: Optional[str] = None,
    time_range: Optional[str] = None
) -> MCSelector:
    """从查询参数创建选择器"""
    selector = MCSelector()
    
    if players:
        selector.set_filters(players=players.split(','))
    
    if modes:
        try:
            mode_list = [int(m.strip()) for m in modes.split(',')]
            selector.set_filters(modes=mode_list)
        except ValueError:
            pass
    
    if time_range:
        selector.set_filters(time_range=parse_time_range(time_range))
    
    return selector

def parse_time_range(time_range: str) -> dict:
    """解析时间范围参数"""
    now = datetime.now()
    
    try:
        if time_range.endswith('d'):
            days = int(time_range[:-1])
            return {'start': now - timedelta(days=days), 'end': now}
        elif time_range.endswith('h'):
            hours = int(time_range[:-1])
            return {'start': now - timedelta(hours=hours), 'end': now}
        elif time_range.endswith('w'):
            weeks = int(time_range[:-1])
            return {'start': now - timedelta(weeks=weeks), 'end': now}
        elif time_range.endswith('m'):
            months = int(time_range[:-1])
            return {'start': now - timedelta(days=months*30), 'end': now}
        else:
            target_date = datetime.strptime(time_range, '%Y-%m-%d')
            return {'start': target_date, 'end': now}
    except (ValueError, TypeError):
        return {'start': now - timedelta(days=30), 'end': now}

@router.get("/top", response_model=APIResponse)
async def get_top_players(
    limit: int = Query(10, description="返回数量", ge=1, le=100),
    mode: Optional[int] = Query(None, description="游戏模式"),
    players: Optional[str] = Query(None, description="玩家筛选，逗号分隔"),
    time_range: Optional[str] = Query(None, description="时间范围，如7d, 30d"),
    rank_type: Literal["exp", "mm"] = Query("exp", description="排行榜类型")
):
    """获取顶级玩家排名"""
    try:
        selector = create_selector_from_query(players=players, time_range=time_range)
        
        if mode is not None:
            selector.set_filters(modes=[mode])
            selector.current_mode = mode
        
        players_data = player_service.get_top_players(selector, limit, rank_type=rank_type)
        
        return APIResponse(
            success=True,
            data=players_data,
            message=f"找到 {len(players_data)} 名玩家",
            timestamp=datetime.now()
        )
        
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )

@router.get("/{player_identifier}", response_model=APIResponse)
async def get_player_info(
    player_identifier: str,
    mode: Optional[int] = Query(None, description="游戏模式"),
    rank_type: Literal["exp", "mm"] = Query("exp", description="排行榜类型")
):
    """获取玩家基本信息"""
    try:
        selector = MCSelector()
        if mode is not None:
            selector.set_filters(modes=[mode])
            selector.current_mode = mode
        
        player_info = player_service.get_player_info(player_identifier, selector, rank_type=rank_type)
        
        if "error" in player_info:
            raise HTTPException(status_code=404, detail=player_info["error"])
        
        return APIResponse(
            success=True,
            data=player_info,
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

@router.get("/{identifier}/profile", response_model=APIResponse)
async def get_player_profile(identifier: str):
    """获取玩家详细资料（头像、头衔、成就、个人信息）"""
    try:
        data = player_service.get_player_profile(identifier)
        if "error" in data:
            raise HTTPException(status_code=404, detail=data["error"])
        return APIResponse(success=True, data=data, timestamp=datetime.now())
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, error=str(e), timestamp=datetime.now())

@router.get("/{player_name}/history", response_model=APIResponse)
async def get_player_history(
    player_name: str,
    days: int = Query(30, description="历史天数", ge=1, le=365),
    mode: Optional[int] = Query(None, description="游戏模式"),
    metric: Literal["exp_rank", "mm_rank", "mmr"] = Query("exp_rank", description="历史指标")
):
    """获取玩家历史排名"""
    try:
        selector = MCSelector()
        if mode is not None:
            selector.current_mode = mode
        elif metric != "mmr":
            selector.current_mode = 0
        
        history_data = player_service.get_player_history(player_name, selector, days, metric=metric)
        
        return APIResponse(
            success=True,
            data=history_data,
            message=f"找到 {len(history_data)} 条历史记录",
            timestamp=datetime.now()
        )
        
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )

@router.get("/search/{keyword}", response_model=APIResponse)
async def search_players(
    keyword: str,
    limit: int = Query(10, description="返回数量", ge=1, le=50),
    mode: Optional[int] = Query(None, description="游戏模式")
):
    """搜索玩家"""
    try:
        selector = MCSelector()
        if mode is not None:
            selector.set_filters(modes=[mode])
            selector.current_mode = mode
        
        search_results = player_service.search_players(keyword, selector, limit)
        
        return APIResponse(
            success=True,
            data=search_results,
            message=f"找到 {len(search_results)} 个匹配玩家",
            timestamp=datetime.now()
        )
        
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )
