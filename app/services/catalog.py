from collections import OrderedDict
from decimal import Decimal
import re
from time import monotonic

from aiogram.types import (
    InputRichBlockParagraph,
    InputRichBlockSectionHeading,
    InputRichBlockTable,
    InputRichMessage,
    RichBlockTableCell,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.models import Branch, Company, Employee
from app.repositories import CompanyRepository, FranchiseeRepository, GradeRuleRepository, ServiceRepository
from app.services.security import EncryptionService
from app.utils.exceptions import AppError
from app.utils.telegram_formatting import blockquote, bold, money, pre
from app.yclients.client import YClientsClient
from app.yclients.types import YClientsProduct

CATALOG_LINE_WIDTH = 52
PRODUCTS_BODY_LIMIT = 3200
PRODUCTS_RICH_PAGE_SIZE = 32
SERVICE_SECTION_ORDER = ("Основные услуги", "Доп. услуги", "Комплексы", "Остальное")
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
_PRODUCTS_CACHE: dict[int, tuple[float, list[YClientsProduct]]] = {}


class CatalogService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._companies = CompanyRepository(session)
        self._franchisees = FranchiseeRepository(session)
        self._grade_rules = GradeRuleRepository(session)
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

        grouped = await self._group_employee_services(employee, services)
        body_lines = _service_catalog_lines(grouped, show_categories=True)

        parts: list[str] = [
            bold("УСЛУГИ"),
            pre(
                [
                    f"Сотрудник   {employee.full_name}",
                    f"Грейд       {employee.category_title or 'не указан'}",
                    f"Позиций     {sum(len(items) for items in grouped.values())}",
                    "Прайс       цены подобраны под мастера",
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

        grouped = await self._group_employee_services(employee, services)
        table_rows: list[list[RichBlockTableCell]] = [
            [
                _table_cell("Услуга", is_header=True),
                _table_cell("Цены", is_header=True),
            ]
        ]
        for category, titles in grouped.items():
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
                    text=(
                        f"Сотрудник: {employee.full_name}. "
                        f"Грейд: {employee.category_title or 'не указан'}. "
                        "Показаны цены, подобранные под мастера."
                    )
                ),
                InputRichBlockTable(cells=table_rows, is_bordered=True, is_striped=True),
            ]
        )

    async def _group_employee_services(self, employee: Employee, services) -> OrderedDict[str, OrderedDict[str, dict[str, object]]]:
        company = await self._companies.get_default()
        rules = await self._grade_rules.list_active(company.id) if company is not None else []
        grade_index, base_price = _employee_grade_position(employee, rules)
        return _group_services(services, grade_index=grade_index, base_price=base_price)

    async def products_text(self, employee: Employee, query: str | None = None) -> str:
        return (await self.products_messages(employee, query=query))[0]

    async def products_rich_messages(self, employee: Employee, query: str | None = None) -> list[InputRichMessage]:
        products = await self._visible_products_for_employee(employee, query=query)
        if not products:
            return [
                InputRichMessage(
                    blocks=[
                        InputRichBlockSectionHeading(text="ТОВАРЫ", size=2),
                        InputRichBlockParagraph(text="Товаров в наличии пока не найдено."),
                    ]
                )
            ]
        chunks = _product_rich_chunks(products, max_items=PRODUCTS_RICH_PAGE_SIZE)
        return [
            _product_rich_message(
                employee=employee,
                products=chunk,
                products_count=len(products),
                part_number=index + 1,
                parts_count=len(chunks),
                query=query,
            )
            for index, chunk in enumerate(chunks)
        ]

    async def products_messages(self, employee: Employee, query: str | None = None) -> list[str]:
        products = await self._visible_products_for_employee(employee, query=query)
        if not products:
            return [
                "\n\n".join(
                    [
                        bold("ТОВАРЫ"),
                        blockquote("Товаров в наличии пока не найдено."),
                    ]
                )
            ]

        products = sorted(products, key=_product_sort_key)
        chunks = _product_catalog_chunks(products, max_chars=PRODUCTS_BODY_LIMIT)
        return [
            _product_message(
                employee=employee,
                lines=lines,
                products_count=len(products),
                part_number=index + 1,
                parts_count=len(chunks),
                query=query,
            )
            for index, lines in enumerate(chunks)
        ]

    async def _visible_products_for_employee(self, employee: Employee, *, query: str | None) -> list[YClientsProduct]:
        products: list[YClientsProduct] = []
        try:
            products = await self._products_from_api(employee)
        except AppError:
            products = []
        if query:
            products = [product for product in products if query.casefold() in product.title.casefold()]
        return sorted(_visible_products(products), key=_product_sort_key)

    async def _products_from_api(self, employee: Employee) -> list[YClientsProduct]:
        company = await self._companies.get_default()
        if company is None:
            return []
        if employee.branch is None:
            return []
        branch_id = employee.branch.yclients_branch_id
        cached_products = _cached_products(branch_id, ttl_seconds=self._settings.yclients_catalog_cache_ttl_seconds)
        if cached_products is not None:
            return cached_products
        client = await self._client_for_branch(company, employee.branch)
        products = await client.list_products(branch_id)
        _PRODUCTS_CACHE[branch_id] = (monotonic(), products)
        return products

    def _client_for_company(self, company: Company) -> YClientsClient:
        return self._client(
            user_token=self._company_user_token(company),
            partner_token=self._encryption.decrypt(company.encrypted_yclients_api_key),
        )

    async def _client_for_branch(self, company: Company, branch: Branch) -> YClientsClient:
        user_token = self._company_user_token(company)
        if branch.owner_telegram_user_id is not None:
            franchisee = await self._franchisees.get_by_telegram_user_id(branch.owner_telegram_user_id)
            if franchisee and not franchisee.is_blocked:
                owner_token = self._encryption.decrypt(franchisee.encrypted_yclients_user_token)
                if owner_token:
                    user_token = owner_token
        return self._client(
            user_token=user_token,
            partner_token=self._encryption.decrypt(company.encrypted_yclients_api_key),
        )

    def _client(self, *, user_token: str | None, partner_token: str | None) -> YClientsClient:
        return YClientsClient(
            base_url=self._settings.yclients_base_url_str,
            partner_token=partner_token or self._settings.yclients_partner_token,
            user_token=user_token,
            timeout_seconds=self._settings.yclients_timeout_seconds,
            product_max_pages=self._settings.yclients_product_max_pages,
        )

    def _company_user_token(self, company: Company) -> str | None:
        return self._encryption.decrypt(company.encrypted_yclients_user_token) or self._settings.yclients_user_token


def _price_range(price_min: Decimal, price_max: Decimal) -> str:
    if price_min == price_max:
        return money(price_min)
    return f"{money(price_min)} - {money(price_max)}"


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    return re.sub(r"\s*\(", " (", title)


def _normalize_title(title: str) -> str:
    return _clean_title(title).casefold().replace("ё", "е")


def _group_services(
    services,
    *,
    grade_index: int | None = None,
    base_price: Decimal | None = None,
) -> OrderedDict[str, OrderedDict[str, dict[str, object]]]:
    grouped: OrderedDict[str, OrderedDict[str, dict[str, object]]] = OrderedDict()
    for service in services:
        category = _service_section(service.title, service.category)
        grouped.setdefault(category, OrderedDict())
        service_key = _normalize_title(service.title)
        item = grouped[category].setdefault(
            service_key,
            {"title": _clean_title(service.title), "prices": set()},
        )
        item["prices"].add((service.price_min, service.price_max))
    if grade_index is not None:
        for titles in grouped.values():
            for item in titles.values():
                item["prices"] = set(_prices_for_grade(item["prices"], grade_index=grade_index, base_price=base_price))
    return _sort_service_groups(grouped)


def _sort_service_groups(
    grouped: OrderedDict[str, OrderedDict[str, dict[str, object]]],
) -> OrderedDict[str, OrderedDict[str, dict[str, object]]]:
    ordered: OrderedDict[str, OrderedDict[str, dict[str, object]]] = OrderedDict()
    categories = [category for category in SERVICE_SECTION_ORDER if category in grouped]
    categories.extend(sorted((category for category in grouped if category not in SERVICE_SECTION_ORDER), key=str.casefold))
    for category in categories:
        ordered[category] = OrderedDict(
            sorted(grouped[category].items(), key=lambda item: str(item[1]["title"]).casefold())
        )
    return ordered


def _employee_grade_position(employee: Employee, rules) -> tuple[int | None, Decimal | None]:
    category = (employee.category_title or "").casefold().replace("ё", "е")
    for index, rule in enumerate(rules):
        rule_category = rule.category_title.casefold().replace("ё", "е")
        if rule_category in category or category in rule_category or str(int(rule.base_price)) in category:
            return index, rule.base_price
    for index, price in enumerate((Decimal("1500"), Decimal("1700"), Decimal("1900"), Decimal("2300"))):
        if str(int(price)) in category:
            return index, price
    aliases = (
        ("старший эксперт", Decimal("2300"), 3),
        ("старший мастер", Decimal("1700"), 1),
        ("эксперт", Decimal("1900"), 2),
        ("мастер", Decimal("1500"), 0),
    )
    for alias, price, index in aliases:
        if alias in category:
            return index, price
    return None, None


def _prices_for_grade(
    prices,
    *,
    grade_index: int,
    base_price: Decimal | None,
) -> list[tuple[Decimal, Decimal]]:
    sorted_prices = sorted(prices, key=lambda price: (price[0], price[1]))
    if not sorted_prices:
        return []
    if base_price is not None:
        exact_prices = [
            price
            for price in sorted_prices
            if price[0] <= base_price <= price[1] or price[0] == base_price or price[1] == base_price
        ]
        if exact_prices:
            return exact_prices
    if len(sorted_prices) <= 1:
        return sorted_prices
    return [sorted_prices[min(grade_index, len(sorted_prices) - 1)]]


def _service_section(title: str, category: str | None) -> str:
    normalized = _normalize_title(" ".join(part for part in (category, title) if part))
    if "+" in title or "комплекс" in normalized or "папа" in normalized:
        return "Комплексы"
    additional_keywords = (
        "воск",
        "камуфляж",
        "тонир",
        "детокс",
        "уход",
        "патчи",
        "уклад",
        "окраш",
        "завив",
        "volcare",
        "маска",
        "шампун",
        "скраб",
    )
    if any(keyword in normalized for keyword in additional_keywords):
        return "Доп. услуги"
    main_keywords = (
        "стриж",
        "брить",
        "бритв",
        "бород",
        "коррекц",
        "шейвер",
    )
    if any(keyword in normalized for keyword in main_keywords):
        return "Основные услуги"
    return "Остальное"


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


def _product_catalog_chunks(products: list[YClientsProduct], *, max_chars: int) -> list[list[str]]:
    chunks: list[list[str]] = []
    lines: list[str] = []
    current_category: str | None = None
    for product in products:
        category = _product_category(product)
        block: list[str] = []
        if not lines or category != current_category:
            if lines:
                block.append("")
            block.append(f"[{category.upper()}]")
        block.extend(_product_lines(product))
        candidate = lines + block
        if lines and len("\n".join(candidate)) > max_chars:
            chunks.append(lines)
            lines = [f"[{category.upper()}]", *_product_lines(product)]
        else:
            lines = candidate
        current_category = category
    if lines:
        chunks.append(lines)
    return chunks


def _product_rich_chunks(products: list[YClientsProduct], *, max_items: int) -> list[list[YClientsProduct]]:
    chunks: list[list[YClientsProduct]] = []
    current: list[YClientsProduct] = []
    for product in products:
        if current and len(current) >= max_items:
            chunks.append(current)
            current = []
        current.append(product)
    if current:
        chunks.append(current)
    return chunks


def _product_message(
    *,
    employee: Employee,
    lines: list[str],
    products_count: int,
    part_number: int,
    parts_count: int,
    query: str | None,
) -> str:
    summary = [
        f"Филиал      {employee.branch.name if employee.branch else 'не указан'}",
        f"В наличии   {products_count}",
        "Фильтр      только в наличии",
        "Исключено   сертификаты",
    ]
    if parts_count > 1:
        summary.append(f"Часть       {part_number} из {parts_count}")
    if query:
        summary.append(f"Поиск       {query}")
    return "\n\n".join([bold("ТОВАРЫ"), pre(summary), pre(lines)])


def _product_rich_message(
    *,
    employee: Employee,
    products: list[YClientsProduct],
    products_count: int,
    part_number: int,
    parts_count: int,
    query: str | None,
) -> InputRichMessage:
    summary_rows = [
        [_table_cell("Филиал", is_header=True), _table_cell(employee.branch.name if employee.branch else "не указан")],
        [_table_cell("В наличии", is_header=True), _table_cell(str(products_count))],
        [_table_cell("Фильтр", is_header=True), _table_cell("только в наличии")],
        [_table_cell("Исключено", is_header=True), _table_cell("сертификаты")],
    ]
    if parts_count > 1:
        summary_rows.append([_table_cell("Часть", is_header=True), _table_cell(f"{part_number} из {parts_count}")])
    if query:
        summary_rows.append([_table_cell("Поиск", is_header=True), _table_cell(query)])

    rows: list[list[RichBlockTableCell]] = [
        [
            _table_cell("Название", is_header=True),
            _table_cell("Цена", is_header=True),
            _table_cell("Остаток", is_header=True),
        ]
    ]
    current_category: str | None = None
    for product in products:
        category = _product_category(product).upper()
        if category != current_category:
            rows.append([_table_cell(category, is_header=True, colspan=3)])
            current_category = category
        rows.append(
            [
                _table_cell(_clean_title(product.title)),
                _table_cell(money(product.price)),
                _table_cell(_stock_text(product.stock_amount)),
            ]
        )
    return InputRichMessage(
        blocks=[
            InputRichBlockSectionHeading(text="ТОВАРЫ", size=2),
            InputRichBlockTable(cells=summary_rows, is_bordered=True, is_striped=True),
            InputRichBlockTable(cells=rows, is_bordered=True, is_striped=True),
        ]
    )


def _visible_products(products: list[YClientsProduct]) -> list[YClientsProduct]:
    return [
        product
        for product in products
        if product.stock_amount > 0 and not _is_certificate_product(product)
    ]


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


def _cached_products(branch_id: int, *, ttl_seconds: int) -> list[YClientsProduct] | None:
    if ttl_seconds <= 0:
        return None
    cached = _PRODUCTS_CACHE.get(branch_id)
    if cached is None:
        return None
    cached_at, products = cached
    if monotonic() - cached_at > ttl_seconds:
        _PRODUCTS_CACHE.pop(branch_id, None)
        return None
    return products
