import json
import os
import subprocess
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now().isoformat()


class CrawlerTaskService:
    """Manage crawler subprocess tasks for API-level tracking."""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or os.getcwd()
        self.logs_dir = os.path.join(self.base_dir, "logs", "crawler_tasks")
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

    def _update_task(self, task_id: str, **updates: Any) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.update(updates)
            task["updated_at"] = _now_iso()
            self._save()

    def _watch_process(self, task_id: str, process: subprocess.Popen) -> None:
        try:
            return_code = process.wait()
            status = "finished" if return_code == 0 else "failed"
            self._update_task(
                task_id,
                status=status,
                exit_code=return_code,
                ended_at=_now_iso(),
            )
        except Exception as exc:
            self._update_task(
                task_id,
                status="failed",
                exit_code=-1,
                ended_at=_now_iso(),
                message=f"watcher error: {exc}",
            )

    def create_task(self, command: List[str], crawler_type: str) -> Dict[str, Any]:
        task_id = uuid.uuid4().hex[:12]
        log_file = os.path.join(self.logs_dir, f"{task_id}.log")
        task = {
            "task_id": task_id,
            "crawler_type": crawler_type,
            "status": "pending",
            "command": command,
            "pid": None,
            "started_at": _now_iso(),
            "ended_at": None,
            "exit_code": None,
            "log_file": log_file,
            "message": None,
            "updated_at": _now_iso(),
        }

        with self._lock:
            self._tasks[task_id] = task
            self._save()

        try:
            log_handle = open(log_file, "a", encoding="utf-8")
            process = subprocess.Popen(
                command,
                cwd=self.base_dir,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
            log_handle.write(f"[{_now_iso()}] command: {' '.join(command)}\n")
            log_handle.flush()
            log_handle.close()

            self._update_task(
                task_id,
                status="running",
                pid=process.pid,
                message="running",
            )

            watcher = threading.Thread(
                target=self._watch_process,
                args=(task_id, process),
                daemon=True,
            )
            watcher.start()
        except Exception as exc:
            self._update_task(
                task_id,
                status="failed",
                exit_code=-1,
                ended_at=_now_iso(),
                message=f"failed to start process: {exc}",
            )

        return self.get_task(task_id) or task

    def list_tasks(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            tasks = list(self._tasks.values())
        if status:
            tasks = [task for task in tasks if task.get("status") == status]
        tasks.sort(key=lambda item: item.get("started_at") or "", reverse=True)
        return tasks[: max(1, min(limit, 500))]

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def read_task_log(self, task_id: str, tail: int = 200) -> Dict[str, Any]:
        task = self.get_task(task_id)
        if not task:
            return {"found": False, "task_id": task_id, "lines": []}

        log_file = task.get("log_file")
        if not log_file or not os.path.exists(log_file):
            return {"found": True, "task_id": task_id, "lines": [], "log_file": log_file}

        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        keep = max(1, min(tail, 2000))
        return {
            "found": True,
            "task_id": task_id,
            "log_file": log_file,
            "lines": [line.rstrip("\n") for line in lines[-keep:]],
        }

    def summarize(self) -> Dict[str, Any]:
        tasks = self.list_tasks(limit=1000)
        running = sum(1 for item in tasks if item.get("status") == "running")
        failed = sum(1 for item in tasks if item.get("status") == "failed")
        finished = sum(1 for item in tasks if item.get("status") == "finished")
        return {
            "total": len(tasks),
            "running": running,
            "failed": failed,
            "finished": finished,
            "latest": tasks[:5],
        }


crawler_task_service = CrawlerTaskService()

