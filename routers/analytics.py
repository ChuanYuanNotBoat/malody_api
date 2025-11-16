# malody_api/routers/analytics.py
from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from datetime import datetime, timedelta

# 修复导入路径 - 改为绝对导入
from malody_api.core.services import AnalysisService
from malody_api.utils.selector import MCSelector
from malody_api.core.models import APIResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])
analysis_service = AnalysisService()

@router.get("/player-trends", response_model=APIResponse)
async def analyze_player_trends(
    start_date: str = Query(..., description="起始日期，格式: YYYY-MM-DD"),
    mode: int = Query(..., description="游戏模式"),
    display_fields: Optional[str] = Query(None, description="显示字段，逗号分隔: rank,lv,exp,acc,combo,pc")
):
    """分析玩家数据变化趋势"""
    try:
        # 解析起始日期
        try:
            start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
        
        # 解析显示字段
        fields = None
        if display_fields:
            fields = [field.strip() for field in display_fields.split(',')]
            valid_fields = ["rank", "lv", "exp", "acc", "combo", "pc"]
            invalid_fields = [field for field in fields if field not in valid_fields]
            if invalid_fields:
                raise HTTPException(
                    status_code=400, 
                    detail=f"无效的显示字段: {', '.join(invalid_fields)}"
                )
        
        selector = MCSelector()
        selector.current_mode = mode
        
        trend_analysis = analysis_service.analyze_player_trends(start_datetime, selector, fields)
        
        if "error" in trend_analysis:
            raise HTTPException(status_code=404, detail=trend_analysis["error"])
        
        return APIResponse(
            success=True,
            data=trend_analysis,
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

@router.get("/chart-trends", response_model=APIResponse)
async def get_chart_trends(
    mode: int = Query(..., description="游戏模式"),
    period: str = Query("months", description="时间段: days, months"),
    creators: Optional[str] = Query(None, description="创作者筛选，逗号分隔"),
    difficulties: Optional[str] = Query(None, description="难度范围，如5-10"),
    statuses: Optional[str] = Query(None, description="状态筛选，逗号分隔")
):
    """获取谱面更新趋势"""
    try:
        selector = MCSelector()
        selector.current_mode = mode
        
        if creators:
            selector.set_filters(players=creators.split(','))
        
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
        
        if period not in ["days", "months"]:
            period = "months"
        
        trend_data = analysis_service.get_chart_trends(selector, period)
        
        return APIResponse(
            success=True,
            data=trend_data,
            message=f"找到 {len(trend_data)} 个时间段的数据",
            timestamp=datetime.now()
        )
        
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )

@router.get("/mode-comparison", response_model=APIResponse)
async def compare_modes(
    modes: str = Query(..., description="要比较的模式，逗号分隔，如0,3,5")
):
    """比较不同模式的谱面数据"""
    try:
        try:
            mode_list = [int(m.strip()) for m in modes.split(',')]
        except ValueError:
            raise HTTPException(status_code=400, detail="模式必须是数字")
        
        # 验证模式有效性
        valid_modes = list(range(10))  # 0-9
        invalid_modes = [m for m in mode_list if m not in valid_modes]
        if invalid_modes:
            raise HTTPException(
                status_code=400, 
                detail=f"无效的模式: {', '.join(map(str, invalid_modes))}"
            )
        
        comparison_data = analysis_service.compare_modes(mode_list)
        
        return APIResponse(
            success=True,
            data=comparison_data,
            message=f"比较了 {len(comparison_data)} 个模式",
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