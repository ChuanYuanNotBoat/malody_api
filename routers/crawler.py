# malody_api/routers/crawler.py
from fastapi import APIRouter, BackgroundTasks, Query, Depends
import subprocess
import os
import sys
import json
from datetime import datetime
from typing import Optional

# 改为绝对导入
from malody_api.core.models import APIResponse
from malody_api.core.security import require_api_key
from malody_api.utils.crawler_manager import crawler_manager

router = APIRouter(
    prefix="/crawler",
    tags=["crawler"],
    dependencies=[Depends(require_api_key)],
)

def run_subprocess(cmd):
    """后台运行子进程"""
    subprocess.run(cmd, capture_output=True)

@router.post("/run", response_model=APIResponse)
async def run_crawler(
    background_tasks: BackgroundTasks,
    crawler_type: str = Query("leaderboard", description="爬虫类型: leaderboard, player, stb"),
    once: bool = Query(True, description="是否只运行一次"),
    limit: Optional[int] = Query(None, description="最大爬取数量（对player和stb有效）"),
    rpm: Optional[int] = Query(None, description="每分钟请求数限制")
):
    """启动爬虫（后台运行）"""
    script_map = {
        "leaderboard": "malody_rankings.py",
        "player": "player_profile_crawler.py",
        "stb": "stb_crawler.py"
    }
    if crawler_type not in script_map:
        return APIResponse(success=False, error="无效的爬虫类型", timestamp=datetime.now())

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    script = os.path.join(base_dir, script_map[crawler_type])
    if not os.path.exists(script):
        return APIResponse(success=False, error=f"爬虫脚本不存在: {script}", timestamp=datetime.now())

    cmd = [sys.executable, script]
    if once:
        cmd.append("--once")
    if limit:
        if crawler_type == "stb":
            cmd.extend(["--max-charts", str(limit)])
        else:
            cmd.extend(["--limit", str(limit)])
    if rpm:
        cmd.extend(["--rpm", str(rpm)])

    background_tasks.add_task(run_subprocess, cmd)
    return APIResponse(success=True, message=f"爬虫 {crawler_type} 已启动", timestamp=datetime.now())

@router.get("/status", response_model=APIResponse)
async def get_crawler_status():
    """获取各爬虫进度状态"""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    status = {
        "cid": {},
        "sid": {},
        "sid_backwards": {},
        "global": {}
    }
    files = [
        ("cid", "cid_progress.json"),
        ("sid", "sid_progress.json"),
        ("sid_backwards", "sid_backwards_progress.json"),
        ("global", "global_progress.bin")
    ]
    for key, fname in files:
        path = os.path.join(base_dir, fname)
        if os.path.exists(path):
            if fname.endswith('.json'):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        status[key] = json.load(f)
                except:
                    status[key] = {"error": "无法解析进度文件"}
            else:
                status[key] = {"exists": True, "size": os.path.getsize(path)}
        else:
            status[key] = {"exists": False}
    return APIResponse(success=True, data=status, timestamp=datetime.now())
