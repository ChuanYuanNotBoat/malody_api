import importlib
from difflib import get_close_matches
from dataclasses import dataclass
from typing import Iterable

from stats_cli.plugins import (
    alias_plugin,
    compare_plugin,
    crawl_status_plugin,
    export_plugin,
    help_plugin,
    history_plugin,
    optimize_plugin,
    player_plugin,
    profile_plugin,
    repair_plugin,
    search_plugin,
    select_plugin,
    stb_compare_plugin,
    stb_creator_details_plugin,
    stb_creator_trends_plugin,
    stb_hot_plugin,
    stb_pie_plugin,
    stb_quality_plugin,
    stb_recent_plugin,
    stb_stabled_by_plugin,
    stb_stats_plugin,
    stb_summary_plugin,
    stb_top_stabilizers_plugin,
    stb_trends_plugin,
    top_chart_plugin,
    top_plugin,
    trend_plugin,
    update_plugin,
    utility_plugin,
)


@dataclass(frozen=True)
class _PluginSpec:
    module: object
    kwargs: tuple[str, ...]


_PLUGIN_SPECS = (
    _PluginSpec(update_plugin, ("colorize", "colors", "base_dir")),
    _PluginSpec(export_plugin, ("colorize", "colors", "db_safe_operation")),
    _PluginSpec(optimize_plugin, ("colorize", "colors", "base_dir")),
    _PluginSpec(crawl_status_plugin, ("colorize", "colors", "get_separator")),
    _PluginSpec(utility_plugin, ("colorize", "colors", "get_separator", "db_safe_operation")),
    _PluginSpec(alias_plugin, ("colorize", "colors", "db_safe_operation")),
    _PluginSpec(help_plugin, ("colorize", "colors", "get_separator", "get_subseparator")),
    _PluginSpec(select_plugin, ("colorize", "colors", "get_separator")),
    _PluginSpec(repair_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
    _PluginSpec(
        top_plugin,
        ("colorize", "colors", "db_safe_operation", "get_separator", "get_terminal_width"),
    ),
    _PluginSpec(top_chart_plugin, ("colorize", "colors", "db_safe_operation")),
    _PluginSpec(trend_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
    _PluginSpec(search_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
    _PluginSpec(stb_stats_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
    _PluginSpec(stb_pie_plugin, ("colorize", "colors", "db_safe_operation")),
    _PluginSpec(stb_recent_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
    _PluginSpec(stb_hot_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
    _PluginSpec(stb_summary_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
    _PluginSpec(stb_quality_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
    _PluginSpec(stb_trends_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
    _PluginSpec(stb_compare_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
    _PluginSpec(stb_stabled_by_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
    _PluginSpec(
        stb_top_stabilizers_plugin,
        ("colorize", "colors", "db_safe_operation", "get_separator"),
    ),
    _PluginSpec(
        stb_creator_details_plugin,
        ("colorize", "colors", "db_safe_operation", "get_separator"),
    ),
    _PluginSpec(stb_creator_trends_plugin, ("colorize", "colors", "db_safe_operation")),
    _PluginSpec(player_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
    _PluginSpec(profile_plugin, ("colorize", "colors", "db_safe_operation")),
    _PluginSpec(history_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
    _PluginSpec(compare_plugin, ("colorize", "colors", "db_safe_operation", "get_separator")),
)


def _install_single_plugin(cls, spec: _PluginSpec, context: dict) -> None:
    kwargs = {key: context[key] for key in spec.kwargs}
    spec.module.install(cls, **kwargs)


def _normalize_module_name(raw_name: str) -> str:
    name = (raw_name or "").strip()
    if not name:
        return ""
    if name in {"all", "*"}:
        return "all"
    if name.startswith("stats_cli.plugins."):
        return name
    if name.endswith("_plugin"):
        return f"stats_cli.plugins.{name}"
    return f"stats_cli.plugins.{name}_plugin"


def _iter_plugin_commands_for_module(cls, module_name: str) -> Iterable[str]:
    for attr_name in dir(cls):
        if not attr_name.startswith("do_"):
            continue
        method = getattr(cls, attr_name, None)
        if callable(method) and getattr(method, "__module__", "") == module_name:
            yield attr_name


def _all_command_names(cls) -> list[str]:
    names = []
    for attr_name in dir(cls):
        if attr_name.startswith("do_"):
            method = getattr(cls, attr_name, None)
            if callable(method):
                names.append(attr_name[3:])
    return sorted(set(names))


def _module_candidates(name_to_spec: dict[str, _PluginSpec]) -> list[str]:
    candidates: set[str] = set()
    for full_name in name_to_spec:
        short_name = full_name.removeprefix("stats_cli.plugins.")
        if short_name.endswith("_plugin"):
            short_name = short_name[: -len("_plugin")]
        candidates.add(short_name)
        candidates.add(full_name)
    return sorted(candidates)


def install_plugins(
    cls,
    *,
    colorize,
    colors,
    db_safe_operation,
    get_separator,
    get_subseparator,
    get_terminal_width,
    base_dir,
):
    context = {
        "colorize": colorize,
        "colors": colors,
        "db_safe_operation": db_safe_operation,
        "get_separator": get_separator,
        "get_subseparator": get_subseparator,
        "get_terminal_width": get_terminal_width,
        "base_dir": base_dir,
    }
    setattr(cls, "_plugin_install_context", context)
    for spec in _PLUGIN_SPECS:
        _install_single_plugin(cls, spec, context)


def reload_plugins(cls, *, module_name=None, command_name=None):
    context = getattr(cls, "_plugin_install_context", None)
    if not context:
        return {"ok": False, "message": "Plugin context is unavailable", "reloaded_modules": []}

    if module_name and command_name:
        return {
            "ok": False,
            "message": "Specify either module_name or command_name, not both",
            "reloaded_modules": [],
        }

    name_to_spec = {spec.module.__name__: spec for spec in _PLUGIN_SPECS}
    module_candidates = _module_candidates(name_to_spec)
    command_candidates = _all_command_names(cls)
    target_modules: list[str]

    if command_name:
        normalized_command = str(command_name).strip().lower()
        if not normalized_command:
            return {
                "ok": False,
                "message": "Command name is empty",
                "reloaded_modules": [],
                "hints": ["Use: reload command <name>"],
            }
        handler = getattr(cls, f"do_{normalized_command}", None)
        if not callable(handler):
            hints: list[str] = []
            module_guess = _normalize_module_name(normalized_command)
            if module_guess in name_to_spec:
                hints.append(f"'{normalized_command}' is a module. Try: reload module {normalized_command}")
            else:
                close_matches = get_close_matches(normalized_command, command_candidates, n=3, cutoff=0.5)
                if close_matches:
                    hints.append("Did you mean: " + ", ".join(close_matches))
            return {
                "ok": False,
                "message": f"Unknown command: {normalized_command}",
                "reloaded_modules": [],
                "hints": hints,
            }
        source_module = getattr(handler, "__module__", "")
        if source_module not in name_to_spec:
            return {
                "ok": False,
                "message": f"Command '{normalized_command}' is not provided by plugin modules",
                "reloaded_modules": [],
                "hints": [],
            }
        target_modules = [source_module]
    else:
        raw_module = str(module_name or "all").strip()
        normalized_module = _normalize_module_name(raw_module)
        if normalized_module == "all":
            target_modules = [spec.module.__name__ for spec in _PLUGIN_SPECS]
        elif normalized_module in name_to_spec:
            target_modules = [normalized_module]
        else:
            hints = []
            if raw_module in {"?", "help", "-h", "--help"}:
                hints.append("Use: reload ?")
            maybe_command = raw_module.lower()
            if hasattr(cls, f"do_{maybe_command}"):
                hints.append(f"'{raw_module}' looks like a command. Try: reload command {raw_module}")
            else:
                close_matches = get_close_matches(raw_module, module_candidates, n=3, cutoff=0.5)
                if close_matches:
                    hints.append("Did you mean module: " + ", ".join(close_matches))
            return {
                "ok": False,
                "message": f"Unknown plugin module: {module_name}",
                "reloaded_modules": [],
                "hints": hints,
            }

    reloaded_modules: list[str] = []
    for current_module_name in target_modules:
        spec = name_to_spec[current_module_name]
        importlib.reload(spec.module)

        for command_attr in list(_iter_plugin_commands_for_module(cls, current_module_name)):
            delattr(cls, command_attr)

        _install_single_plugin(cls, spec, context)
        reloaded_modules.append(current_module_name)

    if len(reloaded_modules) == 1:
        message = f"Reloaded plugin module: {reloaded_modules[0]}"
    else:
        message = f"Reloaded {len(reloaded_modules)} plugin modules"

    return {"ok": True, "message": message, "reloaded_modules": reloaded_modules, "hints": []}
