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
from app.utils.telegram_formatting import blockquote, bold, money, pre, shorten
from app.yclients.client import YClientsClient
from app.yclients.types import YClientsProduct


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
                    blockquote("YCLIENTS пока не вернул услуги для филиала. Проверьте подключение филиала в панели руководителя."),
                ]
            )

        grouped = _group_services(services)

        parts: list[str] = [
            bold("УСЛУГИ"),
            pre(
                [
                    f"Позиций     {len(services)}",
                    "Группировка одинаковые названия",
                ]
            ),
        ]
        show_categories = len(grouped) > 1 or "Без категории" not in grouped
        for category, titles in grouped.items():
            category_lines: list[str] = [f"{'Услуга':30} Цены"]
            if show_categories:
                parts.append(bold(category.upper()))
            for item in titles.values():
                prices = sorted(item["prices"], key=lambda price: (price[0], price[1]))
                price_line = " · ".join(_price_range(price_min, price_max) for price_min, price_max in prices)
                price_chunks = _split_text(price_line, 30)
                category_lines.append(f"{shorten(item['title'], 30):30} {price_chunks[0] if price_chunks else '-'}")
                for chunk in price_chunks[1:]:
                    category_lines.append(f"{'':30} {chunk}")
            parts.append(pre(category_lines))
        return "\n\n".join(parts)

    async def services_rich_message(self, employee: Employee) -> InputRichMessage:
        services = await self._services.list_by_branch(employee.branch_id)
        if not services:
            return InputRichMessage(
                blocks=[
                    InputRichBlockSectionHeading(text="УСЛУГИ", size=2),
                    InputRichBlockParagraph(
                        text="YCLIENTS пока не вернул услуги для филиала. Проверьте подключение филиала в панели руководителя."
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
        warning: str | None = None
        products: list[YClientsProduct] = []
        try:
            products = await self._products_from_api(employee)
        except AppError as exc:
            warning = _products_error_hint(exc.public_message)
        if query:
            products = [product for product in products if query.casefold() in product.title.casefold()]
        if not products:
            digest = [
                "Товары запрашиваются напрямую из YCLIENTS API, без ожидания синхронизации филиала.",
            ]
            if warning:
                digest.append(f"YCLIENTS не отдал товары: {warning}")
            else:
                digest.append("YCLIENTS вернул пустой список товаров.")
            digest.append("Для работы нужны права API key/токена на склад или товары выбранного филиала.")
            return "\n\n".join([bold("ТОВАРЫ"), blockquote(digest)])

        lines = [f"{'Название':30} {'Цена':>10} {'Остаток':>12}"]
        for product in products:
            lines.append(
                f"{shorten(product.title, 30):30} {money(product.price):>10} {_stock_text(product.stock_amount):>12}"
            )
        return "\n\n".join(
            [
                bold("ТОВАРЫ"),
                blockquote("Показываю товары напрямую из YCLIENTS API, без синхронизации филиала."),
                pre(lines),
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


def _split_text(text: str, width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _stock_text(value: Decimal) -> str:
    if value <= 0:
        return "нет"
    if value == value.to_integral_value():
        return f"{int(value)} шт."
    return f"{value.normalize():f} шт."


def _products_error_hint(message: str) -> str:
    lowered = message.casefold()
    if "нет прав на управление филиалом" in lowered or "недостаточно прав" in lowered or "403" in lowered:
        return (
            "YCLIENTS принял User token, но у пользователя нет прав на товары/склад выбранного филиала. "
            "Выдайте доступ к филиалу и права на склад/товары."
        )
    if "401" in lowered or "идентификатор пользователя" in lowered or "user token" in lowered:
        return (
            "YCLIENTS не увидел User token для товаров/склада. "
            "Проверьте, что сохранён полный User token, а не Partner ID или API key."
        )
    return message
