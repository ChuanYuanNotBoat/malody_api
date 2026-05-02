import os
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from malody_api.core.database import get_db_connection
from malody_api.core.models import APIResponse
from malody_api.core.security import require_api_key
from malody_api.core.services.db_maintenance_service import db_maintenance_service

router = APIRouter(prefix="/system", tags=["system"])


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
