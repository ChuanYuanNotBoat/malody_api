from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from .db_maintenance_service import db_maintenance_service
from .quality_service import quality_service


PluginRunner = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


@dataclass
class Plugin:
    plugin_id: str
    name: str
    version: str
    capabilities: List[str]
    config_schema: Dict[str, Any]
    run_schema: Dict[str, Any]
    runner: PluginRunner

    def manifest(self) -> Dict[str, Any]:
        return {
            "id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "capabilities": self.capabilities,
            "config_schema": self.config_schema,
            "run_schema": self.run_schema,
        }


class PluginService:
    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        self.register(
            Plugin(
                plugin_id="analysis.quality_snapshot",
                name="Quality Snapshot",
                version="1.0.0",
                capabilities=["analysis", "quality"],
                config_schema={"type": "object", "properties": {}},
                run_schema={
                    "type": "object",
                    "properties": {
                        "stale_hours": {"type": "integer", "minimum": 1, "maximum": 168}
                    },
                },
                runner=self._run_quality_snapshot,
            )
        )
        self.register(
            Plugin(
                plugin_id="maintenance.db_health",
                name="DB Health Probe",
                version="1.0.0",
                capabilities=["maintenance", "database"],
                config_schema={"type": "object", "properties": {}},
                run_schema={
                    "type": "object",
                    "properties": {
                        "include_history": {"type": "boolean"}
                    },
                },
                runner=self._run_db_health_probe,
            )
        )

    def register(self, plugin: Plugin) -> None:
        self._plugins[plugin.plugin_id] = plugin

    def list_plugins(self) -> List[Dict[str, Any]]:
        return [plugin.manifest() for plugin in self._plugins.values()]

    def get_plugin(self, plugin_id: str) -> Dict[str, Any]:
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            raise KeyError(plugin_id)
        return plugin.manifest()

    def run_plugin(self, plugin_id: str, config: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            raise KeyError(plugin_id)
        result = plugin.runner(config or {}, payload or {})
        return {
            "plugin_id": plugin_id,
            "ok": True,
            "result": result,
        }

    @staticmethod
    def _run_quality_snapshot(_config: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        stale_hours = int(payload.get("stale_hours", 72))
        return quality_service.run_check(stale_hours=stale_hours)

    @staticmethod
    def _run_db_health_probe(_config: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        include_history = bool(payload.get("include_history", False))
        health = db_maintenance_service.get_health()
        if include_history:
            health["maintenance_history"] = db_maintenance_service.get_history(limit=20)
        return health


plugin_service = PluginService()
