import os
import subprocess
from datetime import datetime
from typing import Any, Dict, Optional

try:
    import yaml
except Exception:  # pragma: no cover - fallback for minimal runtime
    yaml = None


def _now_iso() -> str:
    return datetime.now().isoformat()


class AnalysisAppService:
    """Discover and launch external analysis desktop program."""

    def __init__(self, config_file: str = "config.yaml", base_dir: Optional[str] = None):
        self.base_dir = base_dir or os.getcwd()
        self.config_file = os.path.join(self.base_dir, config_file)
        self.default_candidate = os.path.abspath(os.path.join(self.base_dir, "..", "Malody_Analytics_Tool"))

    def _load_yaml(self) -> Dict[str, Any]:
        if yaml is None:
            return {}
        if not os.path.exists(self.config_file):
            return {}
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                payload = yaml.safe_load(f) or {}
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _resolve_path(self, raw_path: Optional[str]) -> str:
        if raw_path:
            if os.path.isabs(raw_path):
                return raw_path
            return os.path.abspath(os.path.join(self.base_dir, raw_path))
        return self.default_candidate

    def discover(self) -> Dict[str, Any]:
        cfg = self._load_yaml()
        analysis_cfg = cfg.get("analysis_app", {}) if isinstance(cfg.get("analysis_app"), dict) else {}
        root = self._resolve_path(analysis_cfg.get("path"))
        entrypoint = analysis_cfg.get("entrypoint") or "main.py"
        launch_cmd = analysis_cfg.get("launch_cmd") or "python main.py"
        app_file = os.path.join(root, entrypoint)
        return {
            "root": root,
            "entrypoint": entrypoint,
            "launch_cmd": launch_cmd,
            "exists": os.path.isdir(root),
            "entry_exists": os.path.exists(app_file),
            "checked_at": _now_iso(),
            "config_file": self.config_file,
        }

    def launch(self, extra_args: Optional[list[str]] = None) -> Dict[str, Any]:
        info = self.discover()
        cmd = info["launch_cmd"].split()
        if extra_args:
            cmd.extend(extra_args)
        if not info["exists"]:
            return {"ok": False, "error": f"analysis app root not found: {info['root']}", "discovery": info}
        if not info["entry_exists"]:
            return {
                "ok": False,
                "error": f"analysis app entry not found: {os.path.join(info['root'], info['entrypoint'])}",
                "discovery": info,
            }
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=info["root"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {
                "ok": True,
                "pid": proc.pid,
                "command": cmd,
                "root": info["root"],
                "launched_at": _now_iso(),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "discovery": info}


analysis_app_service = AnalysisAppService()
