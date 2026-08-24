"""Minimal i18n engine. Catalogs are Python dicts (fa.py, en.py) so they ship
with the code and stay grep-able; admin text overrides come from DB at runtime."""
from __future__ import annotations

from importlib import import_module
from typing import Any

_CATALOGS: dict[str, dict] = {}
_current = "fa"


def load(locale: str) -> None:
    global _current
    if locale not in _CATALOGS:
        _CATALOGS[locale] = import_module(f"mirza.i18n.locales.{locale}").MESSAGES
    _current = locale


def set_locale(locale: str) -> None:
    load(locale)


def t(key: str, /, **fmt) -> str:
    """Dot-path lookup with {format} interpolation; falls back to key."""
    # lazy-load default locale if nothing loaded yet
    if _current not in _CATALOGS:
        load(_current)
    cat = _CATALOGS.get(_current) or {}
    val: Any = cat
    for part in key.split("."):
        if isinstance(val, dict):
            val = val.get(part)
        else:
            val = None
            break
    if val is None:
        return key
    try:
        return str(val).format(**fmt) if fmt else str(val)
    except (KeyError, IndexError, ValueError):
        return str(val)
