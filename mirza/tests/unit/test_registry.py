from __future__ import annotations

import pytest

from mirza.core.registry import PluginRegistry, register_panel


class _Dummy:
    def __init__(self, config=None):
        self.config = config or {}


def test_register_and_lookup():
    r = PluginRegistry()

    @r.register("panel", "fake", "v1")
    class Fake(_Dummy):
        pass

    assert r.get("panel", "fake", "v1") is Fake
    assert ("panel", "fake", "v1") in r.list()


def test_duplicate_registration_raises():
    r = PluginRegistry()
    r.register("panel", "dup")(_Dummy)
    with pytest.raises(ValueError):
        r.register("panel", "dup")(_Dummy)


def test_build_without_factory():
    r = PluginRegistry()

    @r.register("panel", "b")
    class B(_Dummy):
        pass

    inst = r.build("panel", "b", {"url": "x"})
    assert inst.config["url"] == "x"


def test_builtin_adapters_registered():
    from mirza.core.registry import registry

    registry.load_builtin("mirza.panels")
    names = {n for _, n, _ in registry.list("panel")}
    assert {"marzban", "marzneshin", "x-ui", "s-ui", "wgdashboard", "mikrotik"} <= names
    revs = {(n, rv) for _, n, rv in registry.list("panel")}
    assert ("x-ui", "alireza") in revs and ("x-ui", "3x-ui") in revs
