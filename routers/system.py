import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from malody_api.core.database import get_db_connection
from malody_api.core.models import APIResponse
from malody_api.core.security import require_api_key
from malody_api.core.services.analysis_app_service import analysis_app_service
from malody_api.core.services.crawler_task_service import crawler_task_service
from malody_api.core.services.db_maintenance_service import db_maintenance_service
from malody_api.core.services.plugin_service import plugin_service
from malody_api.core.services.quality_service import quality_service
from malody_api.core.services.task_center_service import task_center_service
from malody_api.routers.crawler import run_crawler
from malody_api.utils.query_builder import AdvancedQueryService

router = APIRouter(prefix="/system", tags=["system"])
query_service = AdvancedQueryService()


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "on"}:
            return True
        if v in {"0", "false", "no", "off", ""}:
            return False
    if value is None:
        return default
    return bool(value)


def _as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except Exception:
        return default


def _bridge_crawler_task(unified_task_id: str, crawler_task_id: str) -> None:
    """Mirror crawler task status into unified task center."""
    while True:
        crawler_task = crawler_task_service.get_task(crawler_task_id)
        if not crawler_task:
            task_center_service.mark_failed(unified_task_id, "crawler task not found", error=crawler_task_id)
            return

        st = str(crawler_task.get("status") or "")
        if st in {"pending"}:
            task_center_service.append_event(unified_task_id, "queued", "crawler queued", extra={"crawler_task_id": crawler_task_id})
        elif st in {"running"}:
            task_center_service.append_event(
                unified_task_id,
                "running",
                "crawler running",
                extra={"crawler_task_id": crawler_task_id, "pid": crawler_task.get("pid")},
            )
        elif st in {"finished"}:
            task_center_service.mark_succeeded(
                unified_task_id,
                message="crawler finished",
                result={"crawler_task_id": crawler_task_id, "exit_code": crawler_task.get("exit_code")},
            )
            return
        elif st in {"failed"}:
            task_center_service.mark_failed(
                unified_task_id,
                message="crawler failed",
                error=str(crawler_task.get("message") or "crawler task failed"),
            )
            return

        time.sleep(2)


@router.get("/health", response_model=APIResponse)
async def health_check():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sqlite_master")
        table_count = cursor.fetchone()[0]
        conn.close()
        return APIResponse(
            success=True,
            data={"status": "healthy", "database_tables": table_count, "timestamp": datetime.now()},
            message="system healthy",
            timestamp=datetime.now(),
        )
    except Exception as e:
        return APIResponse(success=False, error=f"system error: {e}", timestamp=datetime.now())


@router.get("/database-info", response_model=APIResponse)
async def get_database_info():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        table_stats = {}
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            table_stats[table] = cursor.fetchone()[0]
        db_path = "malody_rankings.db"
        file_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        conn.close()
        return APIResponse(
            success=True,
            data={
                "tables": tables,
                "table_stats": table_stats,
                "file_size_bytes": file_size,
                "file_size_mb": round(file_size / (1024 * 1024), 2) if file_size > 0 else 0,
                "timestamp": datetime.now(),
            },
            timestamp=datetime.now(),
        )
    except Exception as e:
        return APIResponse(success=False, error=str(e), timestamp=datetime.now())


@router.get("/db/health", response_model=APIResponse)
async def get_db_health():
    try:
        data = db_maintenance_service.get_health()
        return APIResponse(success=True, data=data, timestamp=datetime.now())
    except Exception as e:
        return APIResponse(success=False, error=str(e), timestamp=datetime.now())


@router.post("/db/maintain", response_model=APIResponse, dependencies=[Depends(require_api_key)])
async def run_db_maintenance(
    action: Literal["analyze", "vacuum"] = Query(..., description="maintenance action"),
    confirm: bool = Query(False, description="must be true to execute"),
    dry_run: bool = Query(False, description="only validate and simulate"),
):
    result = db_maintenance_service.run_maintenance(action=action, confirm=confirm, dry_run=dry_run)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "maintenance failed"))
    return APIResponse(success=True, data=result["result"], timestamp=datetime.now())


@router.get("/db/maintain/history", response_model=APIResponse, dependencies=[Depends(require_api_key)])
async def get_db_maintenance_history(limit: int = Query(50, ge=1, le=200)):
    data = db_maintenance_service.get_history(limit=limit)
    return APIResponse(success=True, data={"history": data}, timestamp=datetime.now())


@router.post("/tasks", response_model=APIResponse, dependencies=[Depends(require_api_key)])
async def create_system_task(
    payload: Dict[str, Any] = Body(..., description="Task payload with action and params"),
):
    action = str(payload.get("action") or "").strip()
    params = payload.get("params", {}) if isinstance(payload.get("params"), dict) else {}
    if not action:
        raise HTTPException(status_code=400, detail="action is required")

    scope = action.split(".")[0]
    task = task_center_service.create_task(scope=scope, action=action, message=f"task created: {action}", payload=params)
    task_id = task["task_id"]

    if action == "crawler.run":
        try:
            data = await run_crawler(
                BackgroundTasks(),
                crawler_type=params.get("crawler_type", "leaderboard"),
                once=_as_bool(params.get("once"), True),
                limit=_as_int(params.get("limit")),
                rpm=_as_int(params.get("rpm")),
                uid=params.get("uid"),
                uid_range=params.get("uid_range"),
                from_db=_as_bool(params.get("from_db"), False),
                max_workers=_as_int(params.get("max_workers")),
                days_since_update=_as_int(params.get("days_since_update")),
                source=params.get("source"),
                cid_crawl=_as_bool(params.get("cid_crawl"), False),
                sid_crawl=_as_bool(params.get("sid_crawl"), False),
                retry_failed=_as_bool(params.get("retry_failed"), False),
                start=_as_int(params.get("start")),
                end=_as_int(params.get("end")),
                resume=_as_bool(params.get("resume"), True),
            )
            crawler_task = data.data.get("task", {}) if isinstance(data.data, dict) else {}
            crawler_task_id = crawler_task.get("task_id")
            if not crawler_task_id:
                task_center_service.mark_failed(task_id, "failed to start crawler task", error="missing crawler task_id")
            else:
                task_center_service.mark_running(task_id, "crawler task started")
                task_center_service.append_event(
                    task_id,
                    "running",
                    "crawler task accepted",
                    extra={"crawler_task_id": crawler_task_id},
                )
                watcher = threading.Thread(target=_bridge_crawler_task, args=(task_id, crawler_task_id), daemon=True)
                watcher.start()
        except Exception as exc:
            task_center_service.mark_failed(task_id, "crawler start failed", error=str(exc))
        return APIResponse(success=True, data=task_center_service.get_task(task_id), timestamp=datetime.now())

    if action == "quality.check":
        stale_hours = int(params.get("stale_hours", 72))
        selected_rules = params.get("selected_rules")

        def _runner() -> Dict[str, Any]:
            task_center_service.append_event(task_id, "running", "running quality check", progress=10)
            report = quality_service.run_check(stale_hours=stale_hours, selected_rules=selected_rules)
            task_center_service.append_event(task_id, "running", "quality report ready", progress=90)
            return {"report": report}

        task_center_service.run_in_background(task_id, _runner)
        return APIResponse(success=True, data=task_center_service.get_task(task_id), timestamp=datetime.now())

    if action == "db.maintain":
        maintenance_action = str(params.get("action", "analyze"))
        dry_run = _as_bool(params.get("dry_run"), False)

        def _runner() -> Dict[str, Any]:
            task_center_service.append_event(task_id, "running", f"running db maintenance: {maintenance_action}", progress=20)
            result = db_maintenance_service.run_maintenance(action=maintenance_action, confirm=True, dry_run=dry_run)
            if not result.get("success"):
                raise RuntimeError(result.get("error") or "db maintenance failed")
            return {"result": result.get("result")}

        task_center_service.run_in_background(task_id, _runner)
        return APIResponse(success=True, data=task_center_service.get_task(task_id), timestamp=datetime.now())

    if action == "plugin.run":
        plugin_id = str(params.get("plugin_id") or "")
        config = params.get("config", {}) if isinstance(params.get("config"), dict) else {}
        run_payload = params.get("payload", {}) if isinstance(params.get("payload"), dict) else {}
        if not plugin_id:
            task_center_service.mark_failed(task_id, "plugin_id required", error="plugin_id required")
            return APIResponse(success=True, data=task_center_service.get_task(task_id), timestamp=datetime.now())

        def _runner() -> Dict[str, Any]:
            task_center_service.append_event(task_id, "running", f"running plugin: {plugin_id}", progress=20)
            result = plugin_service.run_plugin(plugin_id, config=config, payload=run_payload)
            return {"result": result}

        task_center_service.run_in_background(task_id, _runner)
        return APIResponse(success=True, data=task_center_service.get_task(task_id), timestamp=datetime.now())

    if action == "query.execute":
        query_payload = {
            "table": params.get("table"),
            "columns": params.get("columns"),
            "filters": params.get("filters"),
            "order_by": params.get("order_by"),
            "group_by": params.get("group_by"),
            "having": params.get("having"),
            "limit": _as_int(params.get("limit"), 100),
            "offset": _as_int(params.get("offset"), 0),
            "distinct": _as_bool(params.get("distinct"), False),
        }

        def _runner() -> Dict[str, Any]:
            task_center_service.append_event(task_id, "running", "executing advanced query", progress=20)
            result = query_service.execute_safe_query(**query_payload)
            if not result.get("success"):
                raise RuntimeError(result.get("error") or "query failed")
            rows = result.get("data", [])
            task_center_service.append_event(task_id, "running", f"query returned {len(rows)} rows", progress=95)
            return {"rows": rows, "query": result.get("query"), "params": result.get("params")}

        task_center_service.run_in_background(task_id, _runner)
        return APIResponse(success=True, data=task_center_service.get_task(task_id), timestamp=datetime.now())

    task_center_service.mark_failed(task_id, f"unsupported action: {action}", error="unsupported action")
    return APIResponse(success=True, data=task_center_service.get_task(task_id), timestamp=datetime.now())


@router.get("/tasks", response_model=APIResponse, dependencies=[Depends(require_api_key)])
async def list_system_tasks(
    scope: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    tasks = task_center_service.list_tasks(scope=scope, status=status, limit=limit)
    return APIResponse(success=True, data={"tasks": tasks, "count": len(tasks)}, timestamp=datetime.now())


@router.get("/tasks/{task_id}", response_model=APIResponse, dependencies=[Depends(require_api_key)])
async def get_system_task(task_id: str):
    task = task_center_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return APIResponse(success=True, data=task, timestamp=datetime.now())


@router.get("/tasks/{task_id}/log", response_model=APIResponse, dependencies=[Depends(require_api_key)])
async def get_system_task_log(
    task_id: str,
    tail: int = Query(200, ge=1, le=5000),
):
    data = task_center_service.read_task_log(task_id, tail=tail)
    if not data.get("found"):
        raise HTTPException(status_code=404, detail="task not found")
    return APIResponse(success=True, data=data, timestamp=datetime.now())


@router.get("/analysis-app/status", response_model=APIResponse)
async def get_analysis_app_status():
    return APIResponse(success=True, data=analysis_app_service.discover(), timestamp=datetime.now())


@router.post("/analysis-app/launch", response_model=APIResponse, dependencies=[Depends(require_api_key)])
async def launch_analysis_app(payload: Dict[str, Any] = Body(default={})):
    extra_args: list[str] = []
    api_base = payload.get("api_base")
    open_task_id = payload.get("open_task_id")
    if api_base:
        extra_args.extend(["--api-base", str(api_base)])
    if open_task_id:
        extra_args.extend(["--open-task-id", str(open_task_id)])
    result = analysis_app_service.launch(extra_args=extra_args)
    return APIResponse(success=result.get("ok", False), data=result, error=result.get("error"), timestamp=datetime.now())
