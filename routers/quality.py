import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from malody_api.core.models import APIResponse
from malody_api.core.services.quality_service import quality_service

router = APIRouter(prefix="/quality", tags=["quality"])

_jobs_lock = threading.Lock()
_quality_jobs: Dict[str, Dict[str, Any]] = {}


def _job_now() -> str:
    return datetime.now().isoformat()


def _save_job(job_id: str, payload: Dict[str, Any]) -> None:
    with _jobs_lock:
        _quality_jobs[job_id] = payload


def _get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _jobs_lock:
        job = _quality_jobs.get(job_id)
        return dict(job) if job else None


def _run_quality_job(job_id: str, stale_hours: int, selected_rules: Optional[List[str]]) -> None:
    started = _get_job(job_id) or {}
    started["status"] = "running"
    started["started_at"] = _job_now()
    _save_job(job_id, started)
    try:
        report = quality_service.run_check(stale_hours=stale_hours, selected_rules=selected_rules)
        _save_job(
            job_id,
            {
                **started,
                "status": "finished",
                "finished_at": _job_now(),
                "report": report,
                "error": None,
            },
        )
    except Exception as exc:
        _save_job(
            job_id,
            {
                **started,
                "status": "failed",
                "finished_at": _job_now(),
                "report": None,
                "error": str(exc),
            },
        )


@router.get("/rules", response_model=APIResponse)
async def get_quality_rules():
    return APIResponse(success=True, data={"rules": quality_service.list_rules()}, timestamp=datetime.now())


@router.post("/check", response_model=APIResponse)
async def run_quality_check(
    stale_hours: int = Query(72, ge=1, le=24 * 30),
    async_mode: bool = Query(False, description="Run check asynchronously and return a job id"),
    selected_rules: Optional[List[str]] = Body(default=None),
):
    if not async_mode:
        report = quality_service.run_check(stale_hours=stale_hours, selected_rules=selected_rules)
        return APIResponse(success=True, data=report, timestamp=datetime.now())

    job_id = uuid.uuid4().hex[:12]
    job = {
        "job_id": job_id,
        "status": "queued",
        "created_at": _job_now(),
        "started_at": None,
        "finished_at": None,
        "stale_hours": stale_hours,
        "selected_rules": selected_rules or [],
        "report": None,
        "error": None,
    }
    _save_job(job_id, job)

    worker = threading.Thread(
        target=_run_quality_job,
        args=(job_id, stale_hours, selected_rules),
        daemon=True,
    )
    worker.start()

    return APIResponse(success=True, data=job, timestamp=datetime.now())


@router.get("/jobs/{job_id}", response_model=APIResponse)
async def get_quality_job(job_id: str):
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="quality job not found")
    return APIResponse(success=True, data=job, timestamp=datetime.now())


@router.get("/report", response_model=APIResponse)
async def get_latest_quality_report():
    report = quality_service.latest_report()
    return APIResponse(success=True, data=report, timestamp=datetime.now())

