"""App entrypoint: builds everything and starts polling (dev) or webhook (prod).

Usage:
    python -m mirza            # long-polling, simplest for small hosts
    python -m mirza --webhook  # aiogram webhook + AIOHTTP server
"""
from __future__ import annotations

import argparse
import asyncio

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from . import __version__
from .bot.handlers import admin as admin_handlers
from .bot.handlers import admin_flows as admin_flows_handlers
from .bot.handlers import user as user_handlers
from .bot.handlers import user_flows as user_flows_handlers
from .bot.middleware import ChannelLockMiddleware, DbSessionMiddleware
from .core.logging_setup import setup_logging
from .core.registry import registry
from .core.settings import get_settings
from .db.session import init_models, make_engine, make_sessionmaker

log = structlog.get_logger(__name__)


def build_dispatcher(sessionmaker, settings) -> Dispatcher:
    dp = Dispatcher()
    dp.message.middleware(DbSessionMiddleware(sessionmaker))
    dp.callback_query.middleware(DbSessionMiddleware(sessionmaker))
    # channel lock: reads setting each time; admins bypassed via AdminFilter order
    async def _lock_channel(session):
        from sqlalchemy import select
        from .db.models import BotSetting

        v = (await session.execute(select(BotSetting.value).where(BotSetting.key == "channel_lock"))).scalar_one_or_none()
        return v or None

    dp.message.middleware(ChannelLockMiddleware(_lock_channel))
    dp.include_router(admin_handlers.router)
    dp.include_router(admin_flows_handlers.router)
    dp.include_router(user_handlers.router)
    dp.include_router(user_flows_handlers.router)
    return dp


async def run(polling: bool = True) -> None:
    settings = get_settings()
    setup_logging(debug=settings.debug)
    registry.load_builtin("mirza.panels")
    registry.load_builtin("mirza.payments")
    n_dropins = registry.load_dropins(settings.plugin_dirs)

    engine = make_engine()
    if settings.db.driver.startswith("sqlite"):
        await init_models(engine)  # dev convenience
    sessionmaker = make_sessionmaker(engine)

    bot = Bot(
        token=settings.telegram.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = build_dispatcher(sessionmaker, settings)

    log.info("boot", version=__version__, plugins_builtin=True, dropins=n_dropins,
             panels=registry.list("panel"))

    if polling:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    else:
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

        from .web.health import build_app

        await bot.set_webhook(
            f"{settings.web.base_url}/webhook/{settings.web.webhook_secret}",
            allowed_updates=dp.resolve_used_update_types(),
        )
        app = build_app(settings, sessionmaker, scheduler=None)
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=f"/webhook/{settings.web.webhook_secret}")
        setup_application(app, dp, bot=bot)
        from aiohttp import web

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, settings.web.listen_host, settings.web.listen_port)
        await site.start()
        log.info("webhook.listening", host=settings.web.listen_host, port=settings.web.listen_port)
        await asyncio.Event().wait()


def main() -> None:
    ap = argparse.ArgumentParser(prog="mirza-bot")
    ap.add_argument("--webhook", action="store_true", help="run in webhook mode")
    args = ap.parse_args()
    asyncio.run(run(polling=not args.webhook))


if __name__ == "__main__":
    main()
