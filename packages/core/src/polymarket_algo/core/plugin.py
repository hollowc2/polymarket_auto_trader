import importlib.util
from importlib.metadata import entry_points
from pathlib import Path


def _discover(group: str) -> dict[str, object]:
    return {ep.name: ep.load() for ep in entry_points(group=group)}


def discover_strategies() -> dict[str, object]:
    return _discover("polymarket_algo.strategies")


def discover_indicators() -> dict[str, object]:
    return _discover("polymarket_algo.indicators")


def load_local_plugins() -> dict[str, object]:
    plugin_dir = Path.home() / ".polymarket-algo" / "plugins"
    loaded: dict[str, object] = {}
    if not plugin_dir.exists():
        return loaded
    for file in plugin_dir.glob("*.py"):
        spec = importlib.util.spec_from_file_location(file.stem, file)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            loaded[file.stem] = module
    return loaded
