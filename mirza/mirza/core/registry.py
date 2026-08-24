"""Plugin registry: decorator-based, runtime discovery.

Replaces the PHP `ManagePanel` type-switch with an open registry:
    @register_panel("marzban", revision="classic")
    class MarzbanClassicPanel(BasePanel): ...

Adapters may live in mirza/panels/ (built-in) or plugins/ dir (drop-in).
"""
from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TypeVar

import structlog

log = structlog.get_logger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class PluginKey:
    kind: str          # "panel" | "payment"
    name: str          # e.g. "marzban", "nowpayments"
    revision: str = "default"  # e.g. "alireza", "3x-ui"


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[PluginKey, type] = {}
        self._factories: dict[PluginKey, Callable[[dict], object]] = {}

    # ---- registration -------------------------------------------------
    def register(
        self,
        kind: str,
        name: str,
        revision: str = "default",
        factory: Callable[[dict], object] | None = None,
    ) -> Callable[[type], type]:
        """Decorator. Duplicate (kind,name,revision) raises - fail fast at boot."""

        def deco(cls: type) -> type:
            key = PluginKey(kind, name, revision)
            if key in self._plugins:
                raise ValueError(f"duplicate plugin registration: {key}")
            self._plugins[key] = cls
            if factory is not None:
                self._factories[key] = factory
            log.debug("plugin.registered", kind=kind, name=name, revision=revision, cls=cls.__name__)
            return cls

        return deco

    # ---- lookup -------------------------------------------------------
    def get(self, kind: str, name: str, revision: str = "default") -> type | None:
        return self._plugins.get(PluginKey(kind, name, revision))

    def list(self, kind: str | None = None) -> list[tuple[str, str, str]]:
        return sorted(
            (k.kind, k.name, k.revision)
            for k in self._plugins
            if kind is None or k.kind == kind
        )

    def build(self, kind: str, name: str, config: dict, revision: str = "default"):
        """Instantiate a plugin; falls back to cls(config=...) when no custom factory."""
        key = PluginKey(kind, name, revision)
        cls = self._plugins.get(key)
        if cls is None:
            raise KeyError(f"no plugin for {key}")
        factory = self._factories.get(key)
        if factory is not None:
            return factory(config)
        return cls(config=config)

    def load_builtin(self, package: str) -> int:
        """Import every module under a builtin package (triggers decorators)."""
        n = 0
        pkg = importlib.import_module(package)
        for mod in pkgutil.iter_modules(pkg.__path__):
            importlib.import_module(f"{package}.{mod.name}")
            n += 1
        return n

    def load_dropins(self, dirs: str) -> int:
        """Load *.py plugin files from directories (colon-separated)."""
        n = 0
        for d in dirs.split(":"):
            p = Path(d)
            if not p.is_dir():
                continue
            for f in sorted(p.glob("*.py")):
                spec = importlib.util.spec_from_file_location(f.stem, f)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    n += 1
                    log.info("plugin.dropin_loaded", file=str(f))
        return n


registry = PluginRegistry()
register_panel = lambda name, revision="default": registry.register("panel", name, revision)  # noqa: E731
register_payment = lambda name, revision="default": registry.register("payment", name, revision)  # noqa: E731
