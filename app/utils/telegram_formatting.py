from collections.abc import Iterable
from decimal import Decimal
from html import escape


def html_escape(value: object) -> str:
    return escape(str(value), quote=False)


def bold(value: object) -> str:
    return f"<b>{html_escape(value)}</b>"


def blockquote(value: str | Iterable[str]) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = "\n".join(value)
    return f"<blockquote>{html_escape(text)}</blockquote>"


def pre(value: str | Iterable[str]) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = "\n".join(value)
    return f"<pre>{html_escape(text)}</pre>"


def money(value: Decimal) -> str:
    amount = int(value.quantize(Decimal("1")))
    return f"{amount:,}".replace(",", " ") + " ₽"


def percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}%"


def shorten(value: object, max_length: int) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    if max_length <= 1:
        return text[:max_length]
    return text[: max_length - 1].rstrip() + "…"


def progress_bar(progress: Decimal, width: int = 12) -> str:
    progress = max(Decimal("0"), min(Decimal("100"), progress))
    filled = int((progress / Decimal("100")) * width)
    return "█" * filled + "░" * (width - filled)
