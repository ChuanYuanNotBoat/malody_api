# malody_api/routers/crawler.py
from fastapi import APIRouter, BackgroundTasks, Query, Depends, HTTPException
import subprocess
import os
import sys
import json
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, Literal

# 改为绝对导入
from malody_api.core.models import APIResponse
from malody_api.core.security import require_api_key
from malody_api.utils.crawler_manager import crawler_manager

router = APIRouter(
    prefix="/crawler",
    tags=["crawler"],
    dependencies=[Depends(require_api_key)],
)

MAX_SAFE_PLAYER_WORKERS = 8
MAX_SAFE_RPM = 120

def run_subprocess(cmd):
    """后台运行子进程"""
    subprocess.run(cmd, capture_output=True)


def _safe_read_json(path: str) -> Tuple[Dict[str, Any], Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return {}, str(e)


def _file_meta(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"exists": False}
    stat = os.stat(path)
    return {
        "exists": True,
        "size": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
    }

@router.post("/run", response_model=APIResponse)
async def run_crawler(
    background_tasks: BackgroundTasks,
    crawler_type: Literal["leaderboard", "player", "stb"] = Query("leaderboard", description="爬虫类型: leaderboard, player, stb"),
    once: bool = Query(True, description="是否只运行一次"),
    limit: Optional[int] = Query(None, description="最大爬取数量（对player和stb有效）"),
    rpm: Optional[int] = Query(None, description="每分钟请求数限制"),
    uid: Optional[str] = Query(None, description="player: 单个UID"),
    uid_range: Optional[str] = Query(None, description="player: UID范围，如 1000-2000"),
    from_db: bool = Query(False, description="player: 从数据库筛选待更新玩家"),
    max_workers: Optional[int] = Query(None, description="player: 最大并发线程"),
    days_since_update: Optional[int] = Query(None, description="player: 未更新时间阈值（天）"),
    source: Optional[str] = Query(None, description="stb: 数据源 all/home/latest/api/newapi"),
    cid_crawl: bool = Query(False, description="stb: 启用CID模式"),
    sid_crawl: bool = Query(False, description="stb: 启用SID模式"),
    retry_failed: bool = Query(False, description="stb: 重试失败队列"),
    start: Optional[int] = Query(None, description="stb: 起始ID（CID/SID）"),
    end: Optional[int] = Query(None, description="stb: 结束ID（CID/SID）"),
    resume: bool = Query(True, description="stb: 是否从进度恢复")
):
    """启动爬虫（后台运行）"""
    script_map = {
        "leaderboard": "malody_rankings.py",
        "player": "player_profile_crawler.py",
        "stb": "stb_crawler.py"
    }
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(base_dir, script_map[crawler_type])
    if not os.path.exists(script):
        raise HTTPException(status_code=500, detail=f"爬虫脚本不存在: {script}")

    cmd = [sys.executable, script]

    # 白名单映射：按爬虫类型控制可用参数，禁止任意透传
    if crawler_type == "leaderboard":
        if once:
            cmd.append("--once")
        unsupported = []
        if any([uid, uid_range, from_db, max_workers, days_since_update, source, cid_crawl, sid_crawl, retry_failed, start is not None, end is not None, resume is not True]):
            unsupported.append("player/stb-only parameters")
        if unsupported:
            raise HTTPException(status_code=400, detail=f"leaderboard 不支持参数: {', '.join(unsupported)}")

    elif crawler_type == "player":
        # player_profile_crawler.py 不支持 --once
        if once is False:
            pass
        if uid:
            cmd.extend(["--uid", uid])
        if uid_range:
            cmd.extend(["--uid-range", uid_range])
        if from_db:
            cmd.append("--from-db")
        if limit is not None:
            cmd.extend(["--limit", str(limit)])
        if max_workers is not None:
            if max_workers <= 0:
                raise HTTPException(status_code=400, detail="max_workers 必须大于 0")
            if max_workers > MAX_SAFE_PLAYER_WORKERS:
                raise HTTPException(
                    status_code=400,
                    detail=f"max_workers 不能超过 {MAX_SAFE_PLAYER_WORKERS}"
                )
            cmd.extend(["--max-workers", str(max_workers)])
        if days_since_update is not None:
            if days_since_update <= 0:
                raise HTTPException(status_code=400, detail="days_since_update 必须大于 0")
            cmd.extend(["--days-since-update", str(days_since_update)])
        if rpm is not None:
            if rpm <= 0:
                raise HTTPException(status_code=400, detail="rpm must be > 0")
            if rpm > MAX_SAFE_RPM:
                raise HTTPException(
                    status_code=400,
                    detail=f"rpm must be <= {MAX_SAFE_RPM}"
                )
            cmd.extend(["--rpm", str(rpm)])

        if any([source, cid_crawl, sid_crawl, retry_failed, start is not None, end is not None, resume is not True]):
            raise HTTPException(status_code=400, detail="player 不支持 stb 参数")

    else:  # stb
        if once:
            cmd.append("--once")
        if limit is not None:
            cmd.extend(["--max-charts", str(limit)])
        if rpm is not None:
            if rpm <= 0:
                raise HTTPException(status_code=400, detail="rpm must be > 0")
            if rpm > MAX_SAFE_RPM:
                raise HTTPException(
                    status_code=400,
                    detail=f"rpm must be <= {MAX_SAFE_RPM}"
                )
            cmd.extend(["--rpm", str(rpm)])
        if source:
            if source not in {"all", "home", "latest", "api", "newapi"}:
                raise HTTPException(status_code=400, detail="source must be one of: all/home/latest/api/newapi")
            cmd.extend(["--source", source])
        if cid_crawl:
            cmd.append("--cid-crawl")
        if sid_crawl:
            cmd.append("--sid-crawl")
        if retry_failed:
            cmd.append("--retry-failed")
        if start is not None:
            if start <= 0:
                raise HTTPException(status_code=400, detail="start 必须大于 0")
            if cid_crawl or (not sid_crawl):
                cmd.extend(["--start-cid", str(start)])
            if sid_crawl:
                cmd.extend(["--start-sid", str(start)])
        if end is not None:
            if end <= 0:
                raise HTTPException(status_code=400, detail="end 必须大于 0")
            if cid_crawl or (not sid_crawl):
                cmd.extend(["--end-cid", str(end)])
            if sid_crawl:
                cmd.extend(["--end-sid", str(end)])
        if not resume:
            cmd.append("--no-resume")

        if any([uid, uid_range, from_db, max_workers, days_since_update]):
            raise HTTPException(status_code=400, detail="stb 不支持 player 参数")

    background_tasks.add_task(run_subprocess, cmd)
    return APIResponse(
        success=True,
        data={"command": cmd},
        message=f"爬虫 {crawler_type} 已启动",
        timestamp=datetime.now()
    )

@router.get("/status", response_model=APIResponse)
async def get_crawler_status():
    """获取各爬虫进度状态"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cid_path = os.path.join(base_dir, "cid_progress.json")
    sid_path = os.path.join(base_dir, "sid_progress.json")
    sid_back_path = os.path.join(base_dir, "sid_backwards_progress.json")
    global_path = os.path.join(base_dir, "global_progress.bin")

    status = {"cid": _file_meta(cid_path), "sid": _file_meta(sid_path), "sid_backwards": _file_meta(sid_back_path), "global": _file_meta(global_path)}

    if status["cid"]["exists"]:
        cid_data, cid_err = _safe_read_json(cid_path)
        if cid_err:
            status["cid"]["error"] = f"无法解析进度文件: {cid_err}"
        else:
            status["cid"]["progress"] = {
                "current": cid_data.get("current_cid"),
                "success": cid_data.get("total_success", 0),
                "errors": cid_data.get("total_errors", 0),
                "retry_queue_size": len(cid_data.get("retry_queue", []) or []),
            }

    if status["sid"]["exists"]:
        sid_data, sid_err = _safe_read_json(sid_path)
        if sid_err:
            status["sid"]["error"] = f"无法解析进度文件: {sid_err}"
        else:
            status["sid"]["progress"] = {
                "current": sid_data.get("current_sid"),
                "songs": sid_data.get("total_songs", 0),
                "charts": sid_data.get("total_charts", 0),
                "empty_songs_size": len(sid_data.get("empty_songs", []) or []),
                "failed_sids_size": len(sid_data.get("failed_sids", []) or []),
            }

    if status["sid_backwards"]["exists"]:
        sb_data, sb_err = _safe_read_json(sid_back_path)
        if sb_err:
            status["sid_backwards"]["error"] = f"无法解析进度文件: {sb_err}"
        else:
            status["sid_backwards"]["progress"] = {
                "current": sb_data.get("current_sid"),
                "last_valid_sid": sb_data.get("last_valid_sid"),
                "songs": sb_data.get("total_songs", 0),
                "charts": sb_data.get("total_charts", 0),
                "failed_sids_size": len(sb_data.get("failed_sids", []) or []),
            }

    return APIResponse(success=True, data=status, timestamp=datetime.now())
