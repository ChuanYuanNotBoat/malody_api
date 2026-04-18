# malody_api/routers/charts.py
from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from datetime import datetime, timedelta
import pandas as pd
import io
from fastapi.responses import StreamingResponse

# 改为绝对导入
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
    
    if creators:
        selector.set_filters(players=creators.split(','))
    
    if modes:
        try:
            mode_list = [int(m.strip()) for m in modes.split(',')]
            selector.set_filters(modes=mode_list)
        except ValueError:
            pass
    
    if difficulties:
        try:
            if '-' in difficulties:
                start, end = difficulties.split('-')
                selector.set_filters(difficulties=[float(start.strip()), float(end.strip())])
            else:
                selector.set_filters(difficulties=[float(difficulties.strip())])
        except ValueError:
            pass
    
    if statuses:
        try:
            status_list = [int(s.strip()) for s in statuses.split(',')]
            selector.set_filters(statuses=status_list)
        except ValueError:
            pass
    
    if time_range:
        selector.set_filters(time_range=parse_time_range(time_range))
    
    return selector

def parse_time_range(time_range: str) -> dict:
    """解析时间范围参数"""
    from datetime import datetime, timedelta
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


def parse_last_time_window(last: str) -> Optional[dict]:
    """解析 --last 风格时间窗口，如 30d/8w/6m/1y"""
    now = datetime.now()
    if not last:
        return None
    try:
        if last.endswith('d'):
            return {"start": now - timedelta(days=int(last[:-1])), "end": now}
        if last.endswith('w'):
            return {"start": now - timedelta(weeks=int(last[:-1])), "end": now}
        if last.endswith('m'):
            return {"start": now - timedelta(days=int(last[:-1]) * 30), "end": now}
        if last.endswith('y'):
            return {"start": now - timedelta(days=int(last[:-1]) * 365), "end": now}
        return None
    except (ValueError, TypeError):
        return None

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


@router.get("/summary", response_model=APIResponse)
async def get_chart_summary(
    mode: Optional[int] = Query(None, description="游戏模式"),
    creators: Optional[str] = Query(None, description="创作者筛选，逗号分隔"),
    difficulties: Optional[str] = Query(None, description="难度范围，如5-10"),
    time_range: Optional[str] = Query(None, description="时间范围，如7d, 30d"),
    statuses: Optional[str] = Query(None, description="状态筛选，逗号分隔"),
    detail_level: str = Query("basic", description="统计粒度: basic, detailed")
):
    """获取谱面综合统计报告"""
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
        level = detail_level if detail_level in ["basic", "detailed"] else "basic"
        summary = chart_service.get_chart_summary(selector, level)
        return APIResponse(success=True, data=summary, timestamp=datetime.now())
    except Exception as e:
        return APIResponse(success=False, error=str(e), timestamp=datetime.now())


@router.get("/quality", response_model=APIResponse)
async def get_chart_quality(
    mode: Optional[int] = Query(None, description="游戏模式"),
    creators: Optional[str] = Query(None, description="创作者筛选，逗号分隔"),
    difficulties: Optional[str] = Query(None, description="难度范围，如5-10"),
    time_range: Optional[str] = Query(None, description="时间范围，如7d, 30d"),
    statuses: Optional[str] = Query(None, description="状态筛选，逗号分隔")
):
    """检查谱面数据质量"""
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
        data = chart_service.get_chart_quality(selector)
        return APIResponse(success=True, data=data, timestamp=datetime.now())
    except Exception as e:
        return APIResponse(success=False, error=str(e), timestamp=datetime.now())


@router.get("/stabilizers/top", response_model=APIResponse)
async def get_top_stabilizers(
    mode: int = Query(-1, description="模式，-1 表示全部模式"),
    limit: int = Query(20, description="返回数量", ge=1, le=100)
):
    """获取顶级稳定者排行榜"""
    try:
        data = chart_service.get_top_stabilizers(mode=mode, limit=limit)
        return APIResponse(
            success=True,
            data=data,
            message=f"找到 {len(data)} 名稳定者",
            timestamp=datetime.now()
        )
    except Exception as e:
        return APIResponse(success=False, error=str(e), timestamp=datetime.now())


@router.get("/creators/{creator_name}/details", response_model=APIResponse)
async def get_creator_details(
    creator_name: str,
    mode: int = Query(-1, description="模式，-1 表示全部模式"),
    status: Optional[int] = Query(None, description="状态筛选：0/1/2"),
    limit: int = Query(100, description="谱面列表上限", ge=1, le=500)
):
    """获取创作者详情及谱面列表"""
    try:
        data = chart_service.get_creator_details(
            creator_name=creator_name,
            mode=mode,
            status=status,
            limit=limit
        )
        return APIResponse(success=True, data=data, timestamp=datetime.now())
    except Exception as e:
        return APIResponse(success=False, error=str(e), timestamp=datetime.now())


@router.get("/creators/{creator_name}/trends", response_model=APIResponse)
async def get_creator_trends(
    creator_name: str,
    period: str = Query("months", description="周期: days, months"),
    mode: int = Query(-1, description="模式，-1 表示全部模式"),
    status: Optional[int] = Query(None, description="状态筛选：0/1/2"),
    since: Optional[str] = Query(None, description="起始时间 YYYY-MM-DD"),
    last: Optional[str] = Query(None, description="相对时间窗口，如 90d/6m")
):
    """获取创作者谱面更新趋势"""
    try:
        p = period if period in ["days", "months"] else "months"
        start_date = None
        end_date = datetime.now()

        if since:
            try:
                start_date = datetime.strptime(since, "%Y-%m-%d")
            except ValueError:
                return APIResponse(
                    success=False,
                    error="since 日期格式应为 YYYY-MM-DD",
                    timestamp=datetime.now()
                )
        elif last:
            window = parse_last_time_window(last)
            if not window:
                return APIResponse(
                    success=False,
                    error="last 格式无效，示例: 30d/8w/6m/1y",
                    timestamp=datetime.now()
                )
            start_date = window["start"]
            end_date = window["end"]

        data = chart_service.get_creator_trends(
            creator_name=creator_name,
            period=p,
            mode=mode,
            status=status,
            start_date=start_date,
            end_date=end_date
        )
        return APIResponse(
            success=True,
            data=data,
            message=f"找到 {len(data)} 个时间段的数据",
            timestamp=datetime.now()
        )
    except Exception as e:
        return APIResponse(success=False, error=str(e), timestamp=datetime.now())

@router.get("/{cid}", response_model=APIResponse)
async def get_chart_detail(cid: int):
    """获取单个谱面的详细信息"""
    try:
        data = chart_service.get_chart_detail(cid)
        if "error" in data:
            raise HTTPException(status_code=404, detail=data["error"])
        return APIResponse(success=True, data=data, timestamp=datetime.now())
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, error=str(e), timestamp=datetime.now())

@router.get("/stabilizers/{player_name}/stats", response_model=APIResponse)
async def get_stabilizer_stats(player_name: str):
    """获取稳定者的统计信息"""
    try:
        data = chart_service.get_stabilizer_stats(player_name)
        return APIResponse(success=True, data=data, timestamp=datetime.now())
    except Exception as e:
        return APIResponse(success=False, error=str(e), timestamp=datetime.now())

@router.get("/stabilizers/{player_name}/charts", response_model=APIResponse)
async def get_stabilizer_charts(
    player_name: str,
    limit: int = Query(50, description="返回数量", ge=1, le=200)
):
    """获取稳定者审核的谱面列表"""
    try:
        data = chart_service.get_stabilizer_charts(player_name, limit)
        return APIResponse(
            success=True,
            data=data,
            message=f"找到 {len(data)} 个谱面",
            timestamp=datetime.now()
        )
    except Exception as e:
        return APIResponse(success=False, error=str(e), timestamp=datetime.now())

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

@router.get("/export/charts")
async def export_charts(
    mode: Optional[int] = Query(None, description="游戏模式"),
    creators: Optional[str] = Query(None, description="创作者筛选，逗号分隔"),
    statuses: Optional[str] = Query(None, description="状态筛选，逗号分隔"),
    format: str = Query("csv", description="导出格式，目前仅支持csv")
):
    """导出谱面数据为CSV文件"""
    try:
        selector = create_chart_selector_from_query(
            creators=creators,
            modes=str(mode) if mode is not None else None,
            statuses=statuses
        )
        where_clause, params = selector.build_chart_sql_where("c")
        query = f"""
            SELECT c.cid, s.title, s.artist, c.version, c.level, c.status,
                   c.creator_name, c.stabled_by_name, c.heat, c.donate_count, c.play_count, c.last_updated
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE {where_clause}
        """
        # 获取数据库连接
        from malody_api.core.database import get_db_connection
        conn = get_db_connection()
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()

        output = io.StringIO()
        df.to_csv(output, index=False, encoding='utf-8')
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=charts.csv"}
        )
    except Exception as e:
        return APIResponse(success=False, error=str(e), timestamp=datetime.now())
