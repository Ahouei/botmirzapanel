from __future__ import annotations

from mirza.i18n import translate as i18n


def test_fa_catalog_loads():
    i18n.set_locale("fa")
    assert i18n.t("users.menu.buy") == "🛒 خرید سرویس"
    assert "{name}" not in i18n.t("admin.login", version="9.9")


def test_en_catalog():
    i18n.set_locale("en")
    assert i18n.t("users.menu.buy") == "🛒 Buy service"


def test_missing_key_returns_key():
    i18n.set_locale("en")
    assert i18n.t("does.not.exist") == "does.not.exist"
