try:
    # Package import path, e.g. `import malody_api.utils.selector`.
    from ..selector import MCSelector
except ImportError:  # pragma: no cover - compatibility for direct script usage
    from selector import MCSelector


__all__ = ["MCSelector"]
