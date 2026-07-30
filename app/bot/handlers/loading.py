import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InputRichMessage, Message

from app.config.logging import get_logger
from app.utils.telegram_formatting import blockquote, bold

logger = get_logger(__name__)

_FRAMES = ("Загрузка", "Загрузка.", "Загрузка..", "Загрузка...")


@dataclass(slots=True)
class RichMessageResult:
    rich_message: InputRichMessage
    fallback_text: str
    reply_markup: Any | None = None


LoadingResult = str | tuple[str, InlineKeyboardMarkup | None] | RichMessageResult


async def answer_with_loading(
    message: Message,
    *,
    title: str,
    detail: str,
    producer: Callable[[], Awaitable[LoadingResult]],
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    loading_message = await message.answer(_loading_text(title, detail, _FRAMES[0]))
    await _finish_with_loading(
        loading_message,
        title=title,
        detail=detail,
        producer=producer,
        reply_markup=reply_markup,
    )


async def edit_with_loading(
    message: Message,
    *,
    title: str,
    detail: str,
    producer: Callable[[], Awaitable[LoadingResult]],
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    await _safe_edit_text(message, _loading_text(title, detail, _FRAMES[0]))
    await _finish_with_loading(
        message,
        title=title,
        detail=detail,
        producer=producer,
        reply_markup=reply_markup,
    )


async def _finish_with_loading(
    message: Message,
    *,
    title: str,
    detail: str,
    producer: Callable[[], Awaitable[LoadingResult]],
    reply_markup: InlineKeyboardMarkup | None,
) -> None:
    animation = asyncio.create_task(_animate_loading(message, title=title, detail=detail))
    try:
        result = await producer()
    except Exception:
        animation.cancel()
        with suppress(asyncio.CancelledError):
            await animation
        with suppress(Exception):
            await _safe_edit_text(message, _loading_text("ОШИБКА ЗАГРУЗКИ", "Попробуйте повторить действие.", _FRAMES[0]))
        raise
    animation.cancel()
    with suppress(asyncio.CancelledError):
        await animation
    if isinstance(result, tuple):
        text, result_markup = result
    elif isinstance(result, RichMessageResult):
        await _send_rich_result(message, result, reply_markup=reply_markup)
        return
    else:
        text = result
        result_markup = reply_markup
    await _safe_edit_text(message, text, reply_markup=result_markup)


async def _animate_loading(message: Message, *, title: str, detail: str) -> None:
    index = 1
    while True:
        await asyncio.sleep(1)
        with suppress(Exception):
            await _safe_edit_text(message, _loading_text(title, detail, _FRAMES[index % len(_FRAMES)]))
        index += 1


def _loading_text(title: str, detail: str, frame: str) -> str:
    return "\n\n".join([bold(title), blockquote([frame, detail])])


async def _safe_edit_text(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


async def _send_rich_result(
    message: Message,
    result: RichMessageResult,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    await _safe_edit_text(
        message,
        result.fallback_text,
        reply_markup=result.reply_markup or reply_markup,
    )
    try:
        await message.bot.send_rich_message(
            chat_id=message.chat.id,
            rich_message=result.rich_message,
            reply_markup=result.reply_markup or reply_markup,
        )
    except Exception as exc:
        logger.warning("rich_message_fallback", error=str(exc)[:300])
