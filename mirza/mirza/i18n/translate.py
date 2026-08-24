"""Minimal i18n engine. Catalogs are Python dicts (fa.py, en.py) so they ship
with the code and stay grep-able; admin text overrides come from DB at runtime."""
from __future__ import annotations

from importlib import import_module
from typing import Any

_CATALOGS: dict[str, dict] = {}
_current = "fa"


def load(locale: str) -> None:
    if locale not in _CATALOGS:
        _CATALOGS[locale] = import_module(f"mirza.i18n.locales.{locale}").MESSAGES
    _current = locale  # noqa


def set_locale(locale: str) -> None:
    global _current
    load(locale)
    _current = locale


def t(key: str, /, **fmt) -> str:
    """Dot-path lookup with {format} interpolation; falls back to key."""
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
    return str(val).format(**fmt) if fmt else str(val)
