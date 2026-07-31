import asyncio
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
import uvicorn

from app.api.app import create_api_app
from app.bot.handlers.router import setup_router
from app.bot.middlewares.database import DatabaseSessionMiddleware
from app.bot.middlewares.errors import ErrorHandlerMiddleware
from app.config.logging import configure_logging, get_logger
from app.config.settings import get_settings
from app.database.session import create_engine, create_session_factory
from app.scheduler.jobs import setup_scheduler
from app.services import build_services

logger = get_logger(__name__)

POLLING_RETRY_INITIAL_SECONDS = 5
POLLING_RETRY_MAX_SECONDS = 300


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        await build_services(session, settings).bootstrap.ensure_default_setup()
        await session.commit()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = _create_storage(settings)
    dispatcher = Dispatcher(storage=storage)
    dispatcher.update.middleware(ErrorHandlerMiddleware())
    dispatcher.update.middleware(DatabaseSessionMiddleware(session_factory, settings))
    dispatcher.include_router(setup_router())

    scheduler = await setup_scheduler(bot=bot, session_factory=session_factory, settings=settings)
    scheduler.start()

    api_task = None
    if settings.internal_api_enabled:
        api = create_api_app(settings=settings, session_factory=session_factory)
        config = uvicorn.Config(
            api,
            host=settings.internal_api_host,
            port=settings.internal_api_port,
            log_level=settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        api_task = asyncio.create_task(server.serve())

    logger.info("bot_started", environment=settings.environment)
    try:
        await _start_polling_with_retries(dispatcher, bot)
    finally:
        scheduler.shutdown(wait=False)
        if api_task:
            api_task.cancel()
            with suppress(asyncio.CancelledError):
                await api_task
        await storage.close()
        await bot.session.close()
        await engine.dispose()


async def _start_polling_with_retries(dispatcher: Dispatcher, bot: Bot) -> None:
    retry_delay = POLLING_RETRY_INITIAL_SECONDS
    allowed_updates = dispatcher.resolve_used_update_types()
    while True:
        try:
            await dispatcher.start_polling(bot, allowed_updates=allowed_updates)
            return
        except TelegramNetworkError as exc:
            logger.warning(
                "telegram_polling_network_error",
                error=str(exc),
                retry_in_seconds=retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, POLLING_RETRY_MAX_SECONDS)


def _create_storage(settings):
    if settings.fsm_storage == "memory":
        logger.warning("memory_fsm_storage_enabled")
        return MemoryStorage()
    return RedisStorage.from_url(settings.redis_url)


if __name__ == "__main__":
    asyncio.run(main())
