from collections import OrderedDict
from decimal import Decimal
import re

from aiogram.types import (
    InputRichBlockParagraph,
    InputRichBlockSectionHeading,
    InputRichBlockTable,
    InputRichMessage,
    RichBlockTableCell,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.models import Company, Employee
from app.repositories import CompanyRepository, ServiceRepository
from app.services.security import EncryptionService
from app.utils.exceptions import AppError
from app.utils.telegram_formatting import blockquote, bold, money, pre
from app.yclients.client import YClientsClient
from app.yclients.types import YClientsProduct

CATALOG_LINE_WIDTH = 52
PRODUCTS_BODY_LIMIT = 3200
PRODUCT_CATEGORY_PRIORITY = (
    "reuzel",
    "volcano",
    "nishman",
    "morgan",
    "london grooming",
    "proraso",
    "estel",
    "graham hill",
    "rebel",
)


class CatalogService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._companies = CompanyRepository(session)
        self._services = ServiceRepository(session)
        self._encryption = EncryptionService(settings)

    async def services_text(self, employee: Employee) -> str:
        services = await self._services.list_by_branch(employee.branch_id)
        if not services:
            return "\n\n".join(
                [
                    bold("УСЛУГИ"),
                    blockquote("Услуги пока не найдены. Проверьте выбранный филиал в панели руководителя."),
                ]
            )

        grouped = _group_services(services)
        show_categories = len(grouped) > 1 or "Без категории" not in grouped
        body_lines = _service_catalog_lines(grouped, show_categories=show_categories)

        parts: list[str] = [
            bold("УСЛУГИ"),
            pre(
                [
                    f"Позиций     {len(services)}",
                    "Формат      названия сгруппированы",
                    "Цены        варианты через точку",
                ]
            ),
            pre(body_lines),
        ]
        return "\n\n".join(parts)

    async def services_rich_message(self, employee: Employee) -> InputRichMessage:
        services = await self._services.list_by_branch(employee.branch_id)
        if not services:
            return InputRichMessage(
                blocks=[
                    InputRichBlockSectionHeading(text="УСЛУГИ", size=2),
                    InputRichBlockParagraph(
                        text="Услуги пока не найдены. Проверьте выбранный филиал в панели руководителя."
                    ),
                ]
            )

        grouped = _group_services(services)
        show_categories = len(grouped) > 1 or "Без категории" not in grouped
        table_rows: list[list[RichBlockTableCell]] = [
            [
                _table_cell("Услуга", is_header=True),
                _table_cell("Цены", is_header=True),
            ]
        ]
        for category, titles in grouped.items():
            if show_categories:
                table_rows.append([_table_cell(category.upper(), is_header=True, colspan=2)])
            for item in titles.values():
                prices = sorted(item["prices"], key=lambda price: (price[0], price[1]))
                price_line = "\n".join(_price_range(price_min, price_max) for price_min, price_max in prices)
                table_rows.append(
                    [
                        _table_cell(str(item["title"])),
                        _table_cell(price_line),
                    ]
                )
        return InputRichMessage(
            blocks=[
                InputRichBlockSectionHeading(text="УСЛУГИ", size=2),
                InputRichBlockParagraph(
                    text=f"Позиций: {len(services)}. Одинаковые названия сгруппированы, цены показаны вариантами."
                ),
                InputRichBlockTable(cells=table_rows, is_bordered=True, is_striped=True),
            ]
        )

    async def products_text(self, employee: Employee, query: str | None = None) -> str:
        products: list[YClientsProduct] = []
        try:
            products = await self._products_from_api(employee)
        except AppError:
            products = []
        if query:
            products = [product for product in products if query.casefold() in product.title.casefold()]
        if not products:
            return "\n\n".join(
                [
                    bold("ТОВАРЫ"),
                    blockquote("Товары пока не найдены. Проверьте выбранный филиал в панели руководителя."),
                ]
            )

        products = sorted(products, key=_product_sort_key)
        lines, hidden_count = _product_catalog_lines(products, max_chars=PRODUCTS_BODY_LIMIT)
        summary = [
            f"Филиал      {employee.branch.name if employee.branch else 'не указан'}",
            f"Позиций     {len(products)}",
            f"Показано    {len(products) - hidden_count}",
        ]
        if query:
            summary.append(f"Фильтр      {query}")
        comment = ["Складские товары показаны выше сертификатов и абонементов."]
        if hidden_count:
            comment.append(f"Не поместилось товаров: {hidden_count}.")
        return "\n\n".join(
            [
                bold("ТОВАРЫ"),
                pre(summary),
                pre(lines),
                blockquote(comment),
            ]
        )

    async def _products_from_api(self, employee: Employee) -> list[YClientsProduct]:
        company = await self._companies.get_default()
        if company is None:
            return []
        if employee.branch is None:
            return []
        client = self._client_for_company(company)
        return await client.list_products(employee.branch.yclients_branch_id)

    def _client_for_company(self, company: Company) -> YClientsClient:
        partner_token = self._encryption.decrypt(company.encrypted_yclients_api_key)
        user_token = self._encryption.decrypt(company.encrypted_yclients_user_token) or self._settings.yclients_user_token
        return YClientsClient(
            base_url=self._settings.yclients_base_url_str,
            partner_token=partner_token or self._settings.yclients_partner_token,
            user_token=user_token,
            timeout_seconds=self._settings.yclients_timeout_seconds,
        )


def _price_range(price_min: Decimal, price_max: Decimal) -> str:
    if price_min == price_max:
        return money(price_min)
    return f"{money(price_min)} - {money(price_max)}"


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    return re.sub(r"\s*\(", " (", title)


def _normalize_title(title: str) -> str:
    return _clean_title(title).casefold().replace("ё", "е")


def _group_services(services) -> OrderedDict[str, OrderedDict[str, dict[str, object]]]:
    grouped: OrderedDict[str, OrderedDict[str, dict[str, object]]] = OrderedDict()
    for service in services:
        category = service.category or "Без категории"
        grouped.setdefault(category, OrderedDict())
        service_key = _normalize_title(service.title)
        item = grouped[category].setdefault(
            service_key,
            {"title": _clean_title(service.title), "prices": set()},
        )
        item["prices"].add((service.price_min, service.price_max))
    return grouped


def _table_cell(text: str, *, is_header: bool = False, colspan: int | None = None) -> RichBlockTableCell:
    return RichBlockTableCell(
        align="left",
        valign="middle",
        text=text,
        is_header=is_header,
        colspan=colspan,
    )


def _service_catalog_lines(grouped: OrderedDict[str, OrderedDict[str, dict[str, object]]], *, show_categories: bool) -> list[str]:
    lines: list[str] = []
    for category, titles in grouped.items():
        if lines:
            lines.append("")
        if show_categories:
            lines.append(f"[{_clean_title(category).upper()}]")
        for item in titles.values():
            if lines and lines[-1] != "":
                lines.append("")
            prices = sorted(item["prices"], key=lambda price: (price[0], price[1]))
            lines.extend(_wrap_text(str(item["title"]), CATALOG_LINE_WIDTH))
            lines.extend(
                _wrap_tokens(
                    [_price_range(price_min, price_max) for price_min, price_max in prices],
                    CATALOG_LINE_WIDTH,
                    indent="  ",
                )
            )
    return lines


def _product_catalog_lines(products: list[YClientsProduct], *, max_chars: int) -> tuple[list[str], int]:
    lines: list[str] = []
    hidden_count = 0
    current_category: str | None = None
    for product in products:
        category = _product_category(product)
        block: list[str] = []
        if category != current_category:
            if lines:
                block.append("")
            block.append(f"[{category.upper()}]")
        block.extend(_product_lines(product))
        candidate = lines + block
        if len("\n".join(candidate)) > max_chars:
            hidden_count += 1
            continue
        lines = candidate
        current_category = category
    if hidden_count:
        tail = ["", f"... ещё товаров: {hidden_count}"]
        if len("\n".join(lines + tail)) <= max_chars + 80:
            lines.extend(tail)
    return lines, hidden_count


def _product_lines(product: YClientsProduct) -> list[str]:
    lines = _wrap_text(_clean_title(product.title), CATALOG_LINE_WIDTH)
    lines.extend(
        _wrap_tokens(
            [f"Цена {money(product.price)}", f"Остаток {_stock_text(product.stock_amount)}"],
            CATALOG_LINE_WIDTH,
            indent="  ",
        )
    )
    return lines


def _wrap_tokens(tokens: list[str], width: int, *, indent: str = "", separator: str = " · ") -> list[str]:
    lines: list[str] = []
    current = ""
    available_width = max(8, width - len(indent))
    for token in tokens:
        candidate = token if not current else f"{current}{separator}{token}"
        if current and len(candidate) > available_width:
            lines.append(f"{indent}{current}".rstrip())
            current = token
        else:
            current = candidate
    if current:
        lines.append(f"{indent}{current}".rstrip())
    return lines


def _wrap_text(text: str, width: int, *, first_indent: str = "", next_indent: str | None = None) -> list[str]:
    next_indent = first_indent if next_indent is None else next_indent
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    current_indent = first_indent
    for word in words[1:]:
        available_width = max(8, width - len(current_indent))
        if len(current) + 1 + len(word) <= available_width:
            current = f"{current} {word}"
        else:
            lines.append(f"{current_indent}{current}".rstrip())
            current = word
            current_indent = next_indent
    lines.append(f"{current_indent}{current}".rstrip())
    return lines


def _stock_text(value: Decimal) -> str:
    if value <= 0:
        return "нет"
    if value == value.to_integral_value():
        return f"{int(value)} шт."
    return f"{value.normalize():f} шт."


def _product_category(product: YClientsProduct) -> str:
    return _clean_title(product.category or "Без категории")


def _product_sort_key(product: YClientsProduct) -> tuple[int, int, int, str, str]:
    stock_group = 0 if product.stock_amount > 0 else 1
    return (
        1 if _is_certificate_product(product) else 0,
        _product_category_rank(product),
        stock_group,
        _product_category(product).casefold(),
        _clean_title(product.title).casefold(),
    )


def _product_category_rank(product: YClientsProduct) -> int:
    text = _product_category(product).casefold()
    for index, marker in enumerate(PRODUCT_CATEGORY_PRIORITY):
        if marker in text:
            return index
    return len(PRODUCT_CATEGORY_PRIORITY)


def _is_certificate_product(product: YClientsProduct) -> bool:
    text = f"{product.title} {product.category or ''}".casefold()
    return any(marker in text for marker in ("сертификат", "абонемент"))
