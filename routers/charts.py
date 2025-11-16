# malody_api/routers/charts.py
from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from datetime import datetime

# 修复导入路径 - 改为绝对导入
from malody_api.core.services import ChartService
from malody_api.utils.selector import MCSelector
from malody_api.core.models import APIResponse, ChartStats, HotChart, CreatorStats

router = APIRouter(prefix="/charts", tags=["charts"])
chart_service = ChartService()

def create_chart_selector_from_query(
    creators: Optional[str] = None,
    modes: Optional[str] = None,
    difficulties: Optional[str] = None,
    time_range: Optional[str] = None,
    statuses: Optional[str] = None
) -> MCSelector:
    """从查询参数创建谱面选择器"""
    selector = MCSelector()
    
    # 创作者筛选
    if creators:
        selector.set_filters(players=creators.split(','))
    
    # 模式筛选
    if modes:
        try:
            mode_list = [int(m.strip()) for m in modes.split(',')]
            selector.set_filters(modes=mode_list)
        except ValueError:
            pass
    
    # 难度筛选
    if difficulties:
        try:
            if '-' in difficulties:
                start, end = difficulties.split('-')
                selector.set_filters(difficulties=[float(start.strip()), float(end.strip())])
            else:
                selector.set_filters(difficulties=[float(difficulties.strip())])
        except ValueError:
            pass
    
    # 状态筛选
    if statuses:
        try:
            status_list = [int(s.strip()) for s in statuses.split(',')]
            selector.set_filters(statuses=status_list)
        except ValueError:
            pass
    
    # 时间范围筛选（从players路由复制parse_time_range函数）
    if time_range:
        selector.set_filters(time_range=parse_time_range(time_range))
    
    return selector

def parse_time_range(time_range: str) -> dict:
    """解析时间范围参数"""
    from datetime import datetime, timedelta
    now = datetime.now()
    
    try:
        if time_range.endswith('d'):  # 天数
            days = int(time_range[:-1])
            return {'start': now - timedelta(days=days), 'end': now}
        elif time_range.endswith('h'):  # 小时
            hours = int(time_range[:-1])
            return {'start': now - timedelta(hours=hours), 'end': now}
        elif time_range.endswith('w'):  # 周数
            weeks = int(time_range[:-1])
            return {'start': now - timedelta(weeks=weeks), 'end': now}
        elif time_range.endswith('m'):  # 月数
            months = int(time_range[:-1])
            return {'start': now - timedelta(days=months*30), 'end': now}
        else:
            # 尝试解析为具体日期
            target_date = datetime.strptime(time_range, '%Y-%m-%d')
            return {'start': target_date, 'end': now}
    except (ValueError, TypeError):
        return {'start': now - timedelta(days=30), 'end': now}

@router.get("/stats", response_model=APIResponse)
async def get_chart_stats(
    mode: Optional[int] = Query(None, description="游戏模式"),
    creators: Optional[str] = Query(None, description="创作者筛选，逗号分隔"),
    difficulties: Optional[str] = Query(None, description="难度范围，如5-10"),
    time_range: Optional[str] = Query(None, description="时间范围，如7d, 30d"),
    statuses: Optional[str] = Query(None, description="状态筛选，逗号分隔 (0=Alpha, 1=Beta, 2=Stable)")
):
    """获取谱面统计信息"""
    try:
        selector = create_chart_selector_from_query(
            creators=creators,
            modes=str(mode) if mode is not None else None,
            difficulties=difficulties,
            time_range=time_range,
            statuses=statuses
        )
        
        if mode is not None:
            selector.current_mode = mode
        
        stats = chart_service.get_chart_stats(selector)
        
        return APIResponse(
            success=True,
            data=stats,
            timestamp=datetime.now()
        )
        
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )

@router.get("/hot", response_model=APIResponse)
async def get_hot_charts(
    limit: int = Query(10, description="返回数量", ge=1, le=50),
    mode: Optional[int] = Query(None, description="游戏模式"),
    sort_by: str = Query("heat", description="排序字段: heat, donate_count, play_count, love_count"),
    creators: Optional[str] = Query(None, description="创作者筛选，逗号分隔"),
    difficulties: Optional[str] = Query(None, description="难度范围，如5-10"),
    statuses: Optional[str] = Query(None, description="状态筛选，逗号分隔")
):
    """获取热门谱面"""
    try:
        selector = create_chart_selector_from_query(
            creators=creators,
            modes=str(mode) if mode is not None else None,
            difficulties=difficulties,
            statuses=statuses
        )
        
        if mode is not None:
            selector.current_mode = mode
        
        hot_charts = chart_service.get_hot_charts(selector, sort_by, limit)
        
        return APIResponse(
            success=True,
            data=hot_charts,
            message=f"找到 {len(hot_charts)} 个热门谱面",
            timestamp=datetime.now()
        )
        
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )

@router.get("/recent", response_model=APIResponse)
async def get_recent_charts(
    days: int = Query(7, description="最近天数", ge=1, le=365),
    limit: int = Query(10, description="返回数量", ge=1, le=50),
    mode: Optional[int] = Query(None, description="游戏模式"),
    creators: Optional[str] = Query(None, description="创作者筛选，逗号分隔"),
    difficulties: Optional[str] = Query(None, description="难度范围，如5-10"),
    statuses: Optional[str] = Query(None, description="状态筛选，逗号分隔")
):
    """获取最近更新的谱面"""
    try:
        selector = create_chart_selector_from_query(
            creators=creators,
            modes=str(mode) if mode is not None else None,
            difficulties=difficulties,
            statuses=statuses
        )
        
        if mode is not None:
            selector.current_mode = mode
        
        recent_charts = chart_service.get_recent_charts(selector, days, limit)
        
        return APIResponse(
            success=True,
            data=recent_charts,
            message=f"找到 {len(recent_charts)} 个最近更新的谱面",
            timestamp=datetime.now()
        )
        
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )

@router.get("/stable-creators", response_model=APIResponse)
async def get_stable_creators(
    limit: int = Query(20, description="返回数量", ge=1, le=100),
    mode: Optional[int] = Query(None, description="游戏模式"),
    creators: Optional[str] = Query(None, description="创作者筛选，逗号分隔"),
    difficulties: Optional[str] = Query(None, description="难度范围，如5-10")
):
    """获取Stable谱面创作者排行榜"""
    try:
        selector = create_chart_selector_from_query(
            creators=creators,
            modes=str(mode) if mode is not None else None,
            difficulties=difficulties
        )
        
        if mode is not None:
            selector.current_mode = mode
        
        stable_creators = chart_service.get_stable_creators(selector, limit)
        
        return APIResponse(
            success=True,
            data=stable_creators,
            message=f"找到 {len(stable_creators)} 个创作者",
            timestamp=datetime.now()
        )
        
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )

@router.get("/search/{keyword}", response_model=APIResponse)
async def search_charts(
    keyword: str,
    limit: int = Query(10, description="返回数量", ge=1, le=50),
    mode: Optional[int] = Query(None, description="游戏模式")
):
    """搜索谱面"""
    try:
        selector = MCSelector()
        if mode is not None:
            selector.set_filters(modes=[mode])
            selector.current_mode = mode
        
        search_results = chart_service.search_charts(keyword, selector, limit)
        
        return APIResponse(
            success=True,
            data=search_results,
            message=f"找到 {len(search_results)} 个匹配谱面",
            timestamp=datetime.now()
        )
        
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )

@router.get("/creators/search/{keyword}", response_model=APIResponse)
async def search_creators(
    keyword: str,
    limit: int = Query(10, description="返回数量", ge=1, le=50),
    mode: Optional[int] = Query(None, description="游戏模式")
):
    """搜索创作者"""
    try:
        selector = MCSelector()
        if mode is not None:
            selector.set_filters(modes=[mode])
            selector.current_mode = mode
        
        search_results = chart_service.search_creators(keyword, selector, limit)
        
        return APIResponse(
            success=True,
            data=search_results,
            message=f"找到 {len(search_results)} 个匹配创作者",
            timestamp=datetime.now()
        )
        
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )