import json
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now().isoformat()


class TaskCenterService:
    """Unified task center for GUI operations and structured task logs."""

    FINAL_STATUSES = {"succeeded", "failed", "cancelled"}

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or os.getcwd()
        self.logs_dir = os.path.join(self.base_dir, "logs", "tasks")
        self.meta_file = os.path.join(self.logs_dir, "tasks.json")
        os.makedirs(self.logs_dir, exist_ok=True)

        self._lock = threading.Lock()
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.meta_file):
            return
        try:
            with open(self.meta_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._tasks = raw
        except Exception:
            self._tasks = {}

    def _save(self) -> None:
        tmp = self.meta_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._tasks, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.meta_file)

    def _update_task(self, task_id: str, **updates: Any) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            task.update(updates)
            task["updated_at"] = _now_iso()
            self._save()
            return dict(task)

    def create_task(
        self,
        scope: str,
        action: str,
        message: str,
        payload: Optional[Dict[str, Any]] = None,
        initial_status: str = "queued",
    ) -> Dict[str, Any]:
        task_id = uuid.uuid4().hex[:12]
        log_file = os.path.join(self.logs_dir, f"{task_id}.jsonl")
        now = _now_iso()
        task = {
            "task_id": task_id,
            "scope": scope,
            "action": action,
            "status": initial_status,
            "message": message,
            "payload": payload or {},
            "progress": None,
            "created_at": now,
            "started_at": None,
            "ended_at": None,
            "updated_at": now,
            "log_file": log_file,
            "error": None,
            "result": None,
        }
        with self._lock:
            self._tasks[task_id] = task
            self._save()
        self.append_event(task_id, "queued", message=message, progress=0)
        return task

    def append_event(
        self,
        task_id: str,
        phase: str,
        message: str,
        progress: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        task = self.get_task(task_id)
        if not task:
            raise KeyError(task_id)
        event = {
            "timestamp": _now_iso(),
            "task_id": task_id,
            "scope": task.get("scope"),
            "phase": phase,
            "message": message,
            "progress": progress,
            "extra": extra or {},
        }
        with open(task["log_file"], "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._update_task(task_id, message=message, progress=progress)
        return event

    def mark_running(self, task_id: str, message: str = "running") -> Optional[Dict[str, Any]]:
        now = _now_iso()
        task = self._update_task(task_id, status="running", started_at=now, message=message, error=None)
        if task:
            self.append_event(task_id, "running", message=message, progress=0)
        return task

    def mark_succeeded(
        self,
        task_id: str,
        message: str = "succeeded",
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        now = _now_iso()
        task = self._update_task(
            task_id,
            status="succeeded",
            ended_at=now,
            message=message,
            result=result or {},
            error=None,
            progress=100,
        )
        if task:
            self.append_event(task_id, "succeeded", message=message, progress=100, extra=result or {})
        return task

    def mark_failed(self, task_id: str, message: str, error: Optional[str] = None) -> Optional[Dict[str, Any]]:
        now = _now_iso()
        task = self._update_task(
            task_id,
            status="failed",
            ended_at=now,
            message=message,
            error=error or message,
        )
        if task:
            self.append_event(task_id, "failed", message=message, extra={"error": error or message})
        return task

    def mark_cancelled(self, task_id: str, message: str = "cancelled") -> Optional[Dict[str, Any]]:
        now = _now_iso()
        task = self._update_task(task_id, status="cancelled", ended_at=now, message=message)
        if task:
            self.append_event(task_id, "cancelled", message=message)
        return task

    def run_in_background(
        self,
        task_id: str,
        runner: Callable[[], Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        task = self.get_task(task_id)
        if not task:
            return None

        def _worker() -> None:
            self.mark_running(task_id)
            try:
                result = runner() or {}
                self.mark_succeeded(task_id, message="task completed", result=result)
            except Exception as exc:
                self.mark_failed(task_id, message="task failed", error=str(exc))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return task

    def list_tasks(
        self,
        *,
        scope: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            tasks = [dict(item) for item in self._tasks.values()]
        if scope:
            tasks = [item for item in tasks if item.get("scope") == scope]
        if status:
            tasks = [item for item in tasks if item.get("status") == status]
        tasks.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return tasks[: max(1, min(limit, 500))]

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def read_task_log(self, task_id: str, tail: int = 200) -> Dict[str, Any]:
        task = self.get_task(task_id)
        if not task:
            return {"found": False, "task_id": task_id, "events": [], "log_file": None}
        log_file = task.get("log_file")
        if not log_file or not os.path.exists(log_file):
            return {"found": True, "task_id": task_id, "events": [], "log_file": log_file}
        events: List[Dict[str, Any]] = []
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        keep = max(1, min(tail, 5000))
        for line in lines[-keep:]:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                events.append({"timestamp": _now_iso(), "phase": "raw", "message": line})
        return {"found": True, "task_id": task_id, "events": events, "log_file": log_file}


task_center_service = TaskCenterService()

