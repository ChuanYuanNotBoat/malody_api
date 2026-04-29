import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List

from ..database import get_db_connection


def _iso_now() -> str:
    return datetime.now().isoformat()


class DBMaintenanceService:
    SUPPORTED_ACTIONS = {"analyze", "vacuum"}

    def __init__(self, db_path: str = "malody_rankings.db"):
        self.db_path = db_path
        self.logs_dir = os.path.join(os.getcwd(), "logs")
        self.history_file = os.path.join(self.logs_dir, "db_maintenance_history.json")
        os.makedirs(self.logs_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._running = False
        self._history: List[Dict[str, Any]] = self._load_history()

    def _load_history(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.history_file):
            return []
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_history(self) -> None:
        tmp = self.history_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._history, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.history_file)

    def _db_size(self) -> int:
        return os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0

    def get_health(self) -> Dict[str, Any]:
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA page_count")
            page_count = int(cursor.fetchone()[0] or 0)
            cursor.execute("PRAGMA page_size")
            page_size = int(cursor.fetchone()[0] or 0)
            cursor.execute("PRAGMA freelist_count")
            freelist_count = int(cursor.fetchone()[0] or 0)
            cursor.execute("PRAGMA quick_check")
            quick_check = cursor.fetchone()[0]

            fragmentation_ratio = 0.0
            if page_count > 0:
                fragmentation_ratio = round((freelist_count / page_count) * 100.0, 2)

            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index'")
            index_count = int(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            table_count = int(cursor.fetchone()[0] or 0)

            suggestions: List[str] = []
            if fragmentation_ratio >= 10.0:
                suggestions.append("vacuum")
            suggestions.append("analyze")

            return {
                "db_path": os.path.abspath(self.db_path),
                "file_size_bytes": self._db_size(),
                "page_count": page_count,
                "page_size": page_size,
                "freelist_count": freelist_count,
                "fragmentation_ratio": fragmentation_ratio,
                "quick_check": quick_check,
                "index_count": index_count,
                "table_count": table_count,
                "suggested_actions": suggestions,
                "running_maintenance": self._running,
                "checked_at": _iso_now(),
            }
        finally:
            conn.close()

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        keep = max(1, min(limit, 200))
        return list(reversed(self._history[-keep:]))

    def run_maintenance(self, action: str, confirm: bool, dry_run: bool = False) -> Dict[str, Any]:
        normalized = (action or "").strip().lower()
        if normalized not in self.SUPPORTED_ACTIONS:
            return {"success": False, "error": f"unsupported action: {action}"}
        if not confirm:
            return {"success": False, "error": "confirm must be true"}

        with self._lock:
            if self._running:
                return {"success": False, "error": "maintenance already running"}
            self._running = True

        started_at = _iso_now()
        before_size = self._db_size()
        record: Dict[str, Any] = {
            "action": normalized,
            "dry_run": dry_run,
            "started_at": started_at,
            "finished_at": None,
            "success": False,
            "error": None,
            "before_size_bytes": before_size,
            "after_size_bytes": before_size,
        }

        try:
            if dry_run:
                record["success"] = True
                record["finished_at"] = _iso_now()
                self._history.append(record)
                self._save_history()
                return {"success": True, "result": record}

            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            try:
                if normalized == "analyze":
                    conn.execute("ANALYZE")
                    conn.commit()
                elif normalized == "vacuum":
                    conn.execute("VACUUM")
            finally:
                conn.close()

            record["success"] = True
            record["after_size_bytes"] = self._db_size()
            record["finished_at"] = _iso_now()
            self._history.append(record)
            self._save_history()
            return {"success": True, "result": record}
        except Exception as exc:
            record["success"] = False
            record["error"] = str(exc)
            record["after_size_bytes"] = self._db_size()
            record["finished_at"] = _iso_now()
            self._history.append(record)
            self._save_history()
            return {"success": False, "error": str(exc), "result": record}
        finally:
            with self._lock:
                self._running = False


db_maintenance_service = DBMaintenanceService()
