from datetime import date
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.loading import RichMessageResult, RichMessagesResult, answer_with_loading, edit_with_loading
from app.bot.keyboards.employee import (
    employee_main_keyboard,
    kpi_month_keyboard,
    notification_settings_keyboard,
    stats_scope_keyboard,
    stats_scope_period_keyboard,
)
from app.services.factory import ServiceContainer
from app.utils.exceptions import AccessDeniedError

router = Router(name="employee")


def _normalize_button_text(value: str | None) -> str:
    text = (value or "").casefold().strip()
    return (
        text.replace("⚙️", "")
        .replace("⚙", "")
        .replace("📋", "")
        .replace("🧴", "")
        .replace("📊", "")
        .replace("🎯", "")
        .replace("📈", "")
        .replace("💇", "")
        .strip()
    )


def _button_text_is(*values: str):
    normalized_values = {_normalize_button_text(value) for value in values}

    def check(message: Message) -> bool:
        return _normalize_button_text(message.text) in normalized_values

    return check


@router.message(_button_text_is("Статистика", "📊 Статистика"))
async def employee_statistics(message: Message, services: ServiceContainer) -> None:
    employee = await _require_employee(message, services)
    related_employees = _current_employee_first(
        await services.connection.get_related_employees(employee),
        employee,
    )
    if len(related_employees) > 1:
        await message.answer(
            "Выберите филиал для статистики.",
            reply_markup=stats_scope_keyboard(related_employees, "month"),
        )
        return

    async def load_stats() -> RichMessageResult:
        try:
            await services.statistics.refresh_period(employee, "month")
        except Exception:
            pass
        return RichMessageResult(
            rich_message=await services.statistics.employee_stats_rich_message(employee, "month"),
            fallback_text=await services.statistics.employee_stats_text(employee, "month", refresh=False),
            reply_markup=stats_scope_period_keyboard(related_employees, "month", scope="employee", scope_id=str(employee.id)),
        )

    await answer_with_loading(
        message,
        title="ЗАГРУЗКА СТАТИСТИКИ",
        detail="Запрашиваю YCLIENTS и собираю период.",
        producer=load_stats,
    )


@router.callback_query(F.data.startswith("empstats:"))
async def employee_statistics_period(callback: CallbackQuery, services: ServiceContainer) -> None:
    current_employee = await services.connection.get_employee_by_telegram_id(callback.from_user.id)
    if current_employee is None:
        await callback.answer("Сначала подключитесь через /start.", show_alert=True)
        return
    period, scope, scope_id = _parse_stats_callback(callback.data)
    related_employees = _current_employee_first(
        await services.connection.get_related_employees(current_employee),
        current_employee,
    )
    scope_employees = _scope_employees(related_employees, current_employee, scope, scope_id)
    if not scope_employees:
        await callback.answer("Этот филиал недоступен для вашего аккаунта.", show_alert=True)
        return
    scope = scope or "employee"
    scope_id = scope_id or str(current_employee.id)
    await callback.answer()

    async def load_stats() -> RichMessageResult:
        try:
            await services.statistics.refresh_employees_period(scope_employees, period)
        except Exception:
            pass
        return RichMessageResult(
            rich_message=await services.statistics.employee_scope_stats_rich_message(scope_employees, period),
            fallback_text="\n\n".join(await services.statistics.employee_scope_stats_text(scope_employees, period, refresh=False)),
            reply_markup=stats_scope_period_keyboard(
                related_employees,
                period,
                scope=scope,
                scope_id=scope_id,
            ),
        )

    await edit_with_loading(
        callback.message,
        title="ЗАГРУЗКА СТАТИСТИКИ",
        detail="Обновляю выбранный период.",
        producer=load_stats,
    )


@router.message(_button_text_is("KPI", "🎯 KPI"))
async def employee_kpi(message: Message, services: ServiceContainer) -> None:
    employee = await _require_employee(message, services)

    async def load_kpi() -> RichMessageResult:
        period = "month"
        month = _month_from_period(period)
        try:
            await services.statistics.refresh_period(employee, period)
        except Exception:
            pass
        return RichMessageResult(
            rich_message=await services.kpi.employee_kpi_rich_message(employee, month=month),
            fallback_text=await services.kpi.employee_kpi_text(employee, month=month, refresh=False),
            reply_markup=kpi_month_keyboard(period),
        )

    await answer_with_loading(
        message,
        title="ЗАГРУЗКА KPI",
        detail="Обновляю месяц и пересчитываю процент.",
        producer=load_kpi,
    )


@router.callback_query(F.data.startswith("empkpi:"))
async def employee_kpi_month(callback: CallbackQuery, services: ServiceContainer) -> None:
    employee = await services.connection.get_employee_by_telegram_id(callback.from_user.id)
    if employee is None:
        await callback.answer("Сначала подключитесь через /start.", show_alert=True)
        return
    period = callback.data.split(":", maxsplit=1)[1]
    month = _month_from_period(period)
    await callback.answer()

    async def load_kpi() -> RichMessageResult:
        try:
            await services.statistics.refresh_period(employee, period)
        except Exception:
            pass
        return RichMessageResult(
            rich_message=await services.kpi.employee_kpi_rich_message(employee, month=month),
            fallback_text=await services.kpi.employee_kpi_text(employee, month=month, refresh=False),
            reply_markup=kpi_month_keyboard(period),
        )

    await edit_with_loading(
        callback.message,
        title="ЗАГРУЗКА KPI",
        detail="Обновляю выбранный месяц.",
        producer=load_kpi,
    )


@router.message(_button_text_is("Grade Up", "📈 Grade Up"))
async def employee_grade(message: Message, services: ServiceContainer) -> None:
    employee = await _require_employee(message, services)

    async def load_grade() -> RichMessageResult:
        fallback_text = await services.grade.grade_text(employee)
        return RichMessageResult(
            rich_message=await services.grade.grade_rich_message(employee),
            fallback_text=fallback_text,
        )

    await answer_with_loading(
        message,
        title="ЗАГРУЗКА GRADE UP",
        detail="Считаю прогресс до следующей категории.",
        producer=load_grade,
    )


@router.message(_button_text_is("Услуги", "💇 Услуги"))
async def employee_services(message: Message, services: ServiceContainer) -> None:
    employee = await _require_employee(message, services)

    async def load_services() -> RichMessageResult:
        return RichMessageResult(
            rich_message=await services.catalog.services_rich_message(employee),
            fallback_text=await services.catalog.services_text(employee),
        )

    await answer_with_loading(
        message,
        title="ЗАГРУЗКА УСЛУГ",
        detail="Группирую прайс филиала.",
        producer=load_services,
    )


@router.message(_button_text_is("Продажи", "Товары", "🧴 Товары"))
async def employee_products(message: Message, services: ServiceContainer) -> None:
    employee = await _require_employee(message, services)

    async def load_products() -> RichMessagesResult:
        return RichMessagesResult(
            rich_messages=await services.catalog.products_rich_messages(employee),
            fallback_messages=await services.catalog.products_messages(employee),
        )

    await answer_with_loading(
        message,
        title="ЗАГРУЗКА ПРОДАЖ",
        detail="Запрашиваю позиции напрямую из YCLIENTS API.",
        producer=load_products,
    )


@router.message(_button_text_is("Регламент", "📋 Регламент"))
async def employee_regulation(message: Message, services: ServiceContainer) -> None:
    await _require_employee(message, services)
    file_id, file_name, caption = await services.admin.regulation_document()
    if file_id:
        await message.answer_document(
            file_id,
            caption=caption or f"Регламент: {file_name or 'документ'}",
        )
        return
    await message.answer(await services.admin.regulation_text())


@router.message(_button_text_is("Настройки", "⚙ Настройки", "⚙️ Настройки", "Настройки уведомлений"))
async def employee_settings(message: Message, services: ServiceContainer) -> None:
    employee = await _require_employee(message, services)
    if employee.telegram_user is None:
        raise AccessDeniedError("Сначала подключитесь через /start.")
    settings = await services.notifications.get_or_create(employee.telegram_user)
    await message.answer(
        await services.notifications.settings_text(employee.telegram_user),
        reply_markup=notification_settings_keyboard(settings),
    )


@router.callback_query(F.data.startswith("notify:"))
async def toggle_notification(callback: CallbackQuery, services: ServiceContainer) -> None:
    employee = await services.connection.get_employee_by_telegram_id(callback.from_user.id)
    if employee is None or employee.telegram_user is None:
        await callback.answer("Сначала подключитесь через /start.", show_alert=True)
        return
    field_name = callback.data.split(":", maxsplit=1)[1]
    settings = await services.notifications.toggle(employee.telegram_user, field_name)
    value = getattr(settings, field_name)
    await callback.message.edit_text(
        await services.notifications.settings_text(employee.telegram_user),
        reply_markup=notification_settings_keyboard(settings),
    )
    await callback.answer("Включено" if value else "Выключено")


async def _require_employee(message: Message, services: ServiceContainer):
    employee = await services.connection.get_employee_by_telegram_id(message.from_user.id)
    if employee is None:
        raise AccessDeniedError("Сначала подключитесь через /start.")
    return employee


def _month_from_period(period: str) -> date:
    value = (period or "").strip()
    if len(value) == 9 and value.startswith("m"):
        try:
            return date(int(value[1:5]), int(value[5:7]), 1)
        except ValueError:
            pass
    return date.today().replace(day=1)


def _parse_stats_callback(data: str | None) -> tuple[str, str | None, str | None]:
    parts = (data or "").split(":")
    period = parts[1] if len(parts) > 1 else "month"
    scope = parts[2] if len(parts) > 2 else None
    scope_id = parts[3] if len(parts) > 3 else None
    return period, scope, scope_id


def _current_employee_first(employees: list, current_employee) -> list:
    by_id = {employee.id: employee for employee in employees}
    by_id[current_employee.id] = current_employee
    ordered = [by_id.pop(current_employee.id)]
    ordered.extend(sorted(by_id.values(), key=lambda item: (item.branch.name if item.branch else "", item.full_name)))
    return ordered


def _scope_employees(
    related_employees: list,
    current_employee,
    scope: str | None,
    scope_id: str | None,
) -> list:
    if scope == "all":
        return related_employees
    if scope == "employee" and scope_id:
        try:
            employee_id = UUID(scope_id)
        except ValueError:
            return []
        return [employee for employee in related_employees if employee.id == employee_id]
    return [current_employee]
