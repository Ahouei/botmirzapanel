"""Legacy MySQL → clean-schema importer (botmirzapanel PHP DB → mirza-bot).

Run:  python -m mirza.tools.import_legacy --dsn mysql+pymysql://user:pass@host/dbname
Maps every legacy table per PARITY.md. Idempotent-ish: re-inserts are skipped
by primary key conflicts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mirza.db.models import (
    Admin,
    Category,
    Discount,
    HelpEntry,
    Invoice,
    PanelServer,
    PaymentReport,
    Product,
    User,
)

log = structlog.get_logger(__name__)

PANEL_TYPE_MAP = {  # legacy `type` -> (plugin, revision)
    "marzban": ("marzban", "classic"),
    "marzneshin": ("marzneshin", "default"),
    "x-ui": ("x-ui", "3x-ui"),
    "alireza": ("x-ui", "alireza"),
    "s_ui": ("s-ui", "default"),
    "wgdashboard": ("wgdashboard", "default"),
    "mikrotik": ("mikrotik", "rest"),
}


async def run(mysql_dsn: str, pg_dsn: str) -> dict:
    src = create_engine(mysql_dsn.replace("+asyncpg", "+pymysql"))
    dst_engine = create_async_engine(pg_dsn)
    Session = async_sessionmaker(dst_engine, expire_on_commit=False)
    stats: dict[str, int] = {}

    with src.connect() as c:
        # users ---------------------------------------------------------
        rows = c.execute(text(
            "SELECT id, ref_code, step, limit_usertest, User_Status, number, Balance,"
            " pagenumber, username, affiliatescount, affiliates, verify, description_blocking"
            " FROM user"
        )).mappings().all()
        async with Session() as s:
            for r in rows:
                if await s.get(User, int(r["id"])):
                    continue
                s.add(User(
                    id=int(r["id"]),
                    ref_code=(r["ref_code"] or secrets.token_hex(16))[:32],
                    step=r["step"] or "none",
                    status=r["User_Status"] or "Active",
                    balance=int(float(r["Balance"] or 0)),
                    phone_number=(r["number"] or "")[:30] or None,
                    username=(r["username"] or "none")[:250],
                    test_limit=int(r["limit_usertest"] or 0),
                    referral_count=int(float(r["affiliatescount"] or 0)),
                    referred_by=int(float(r["affiliates"])) if r["affiliates"] not in (None, "", "0") else None,
                    verified=str(r["verify"]) == "1",
                    blocked_reason=r["description_blocking"],
                ))
            stats["users"] = len(rows)
            await s.commit()

        # panels ----------------------------------------------------------
        with_src = c.execute(text("SELECT * FROM marzban_panel")).mappings().all()
        async with Session() as s:
            for r in with_src:
                plugin, rev = PANEL_TYPE_MAP.get((r["type"] or "").lower(), ("marzban", "classic"))
                exists = (
                    await s.execute(select_by_name(r["name_panel"]))
                ).scalar_one_or_none()
                if exists:
                    continue
                s.add(PanelServer(
                    name=r["name_panel"],
                    url=r["url_panel"],
                    username=r["username_panel"],
                    password=r["password_panel"],
                    plugin=plugin,
                    revision=rev,
                    enabled=(r["status"] or "activepanel") == "activepanel",
                    allow_test=(r["statusTest"] or "") == "ontestshowpanel",
                    sub_url_base=r.get("linksubx"),
                    inbound_id=r.get("inboundid"),
                    username_method=r.get("MethodUsername") or "random",
                    on_hold=(r.get("onholdstatus") or "") == "onhold",
                    extra={"proxies": _maybe_json(r.get("proxies")), "inbounds": _maybe_json(r.get("inbounds"))},
                ))
            stats["panels"] = len(with_src)
            await s.commit()

        # products / categories -------------------------------------------
        prods = c.execute(text("SELECT * FROM product")).mappings().all()
        cats = c.execute(text("SELECT * FROM category")).mappings().all()
        async with Session() as s:
            cat_map = {}
            for cr in cats:
                cat = Category(title=(cr.get("name_category") or cr.get("title") or "cat")[:200])
                s.add(cat)
                await s.flush()
                cat_map[str(cr.get("id"))] = cat.id
            n = 0
            for r in prods:
                s.add(Product(
                    code=(r.get("code_product") or None),
                    name=(r.get("name_product") or f"prod-{r['id']}")[:200],
                    price=int(float(r.get("price_product") or 0)),
                    volume_gb=int(float(r.get("Volume_constraint") or 0)),
                    location=r.get("Location"),
                    duration_days=int(float(r.get("Service_time") or 30)),
                    category_id=cat_map.get(str(r.get("Category"))),
                ))
                n += 1
            stats["products"] = n
            stats["categories"] = len(cats)
            await s.commit()

        # invoices ----------------------------------------------------------
        invs = c.execute(text("SELECT * FROM invoice")).mappings().all()
        async with Session() as s:
            n = 0
            for r in invs:
                iid = (r.get("id_invoice") or f"imp{n}")[:64]
                if await s.get(Invoice, iid):
                    continue
                s.add(Invoice(
                    id=iid,
                    user_id=int(float(r["id_user"])) if r.get("id_user") else None,
                    product_name=r.get("name_product"),
                    panel_name=r.get("Service_location"),
                    price=int(float(r.get("price_product") or 0)),
                    volume_gb=int(float(r.get("Volume") or 0)) if str(r.get("Volume") or "").replace(".", "").isdigit() else 0,
                    duration_days=_days_or_zero(r.get("Service_time")),
                    service_username=r.get("username"),
                    config_payload={"legacy_user_info": r.get("user_info")},
                    status=_norm_status(r.get("Status")),
                ))
                n += 1
            stats["invoices"] = n
            await s.commit()

        # payments / discounts / admins / settings ---------------------------
        pays = c.execute(text("SELECT * FROM Payment_report")).mappings().all()
        discs = c.execute(text("SELECT * FROM Discount")).mappings().all()
        admins = c.execute(text("SELECT * FROM admin")).mappings().all()
        helps = c.execute(text("SELECT * FROM help")).mappings().all()
        async with Session() as s:
            for r in pays:
                s.add(PaymentReport(
                    order_id=str(r.get("id_order"))[:60],
                    user_id=int(float(r.get("id_user") or 0)),
                    price=int(float(r.get("price") or 0)),
                    gateway="legacy",
                    payment_status="paid" if str(r.get("payment_Status")) == "paid" else "pending",
                ))
            for r in discs:
                s.add(Discount(code=str(r.get("code"))[:60], amount=int(float(r.get("amount") or 0)),
                               usage_limit=int(float(r.get("usable_count") or 1))))
            for r in admins:
                try:
                    s.merge(Admin(id=int(r["id_admin"])))
                except Exception:
                    pass
            for i, r in enumerate(helps):
                s.add(HelpEntry(title=(r.get("name") or f"help{i}")[:200], body=r.get("description") or ""))
            stats["payments"] = len(pays)
            stats["discounts"] = len(discs)
            stats["admins"] = len(admins)
            stats["help"] = len(helps)
            await s.commit()

    await dst_engine.dispose()
    return stats


def select_by_name(name):
    from sqlalchemy import select

    from mirza.db.models import PanelServer

    return select(PanelServer).where(PanelServer.name == name)


def _maybe_json(v):
    if not v:
        return None
    try:
        return json.loads(v)
    except ValueError:
        return {"raw": v}


def _days_or_zero(v):
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _norm_status(v):
    v = (v or "").lower()
    return v if v in ("active", "end_of_time", "end_of_volume", "deleted", "expired", "sendedwarn") else "active"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mysql-dsn", required=True)
    ap.add_argument("--pg-dsn", default="postgresql+asyncpg://mirza@localhost/mirza")
    args = ap.parse_args()
    print(asyncio.run(run(args.mysql_dsn, args.pg_dsn)))
