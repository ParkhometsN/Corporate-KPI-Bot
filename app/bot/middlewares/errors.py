from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from app.config.logging import get_logger
from app.utils.exceptions import AppError

logger = get_logger(__name__)


class ErrorHandlerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except AppError as exc:
            await _answer(event, exc.public_message)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                await _answer_not_modified(event)
                return None
            if "query is too old" in str(exc) or "query ID is invalid" in str(exc):
                logger.warning("telegram_callback_answer_expired")
                return None
            logger.exception("telegram_bad_request")
            await _answer(event, "Telegram отклонил действие. Попробуйте ещё раз.")
        except Exception:
            logger.exception("telegram_handler_failed")
            await _answer(event, "Произошла ошибка. Команда уже записана в лог, попробуйте ещё раз.")


async def _answer(event: Any, text: str) -> None:
    if isinstance(event, Message):
        await event.answer(text)
    elif isinstance(event, CallbackQuery):
        await event.answer(text, show_alert=True)


async def _answer_not_modified(event: Any) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer("Уже открыто.")
