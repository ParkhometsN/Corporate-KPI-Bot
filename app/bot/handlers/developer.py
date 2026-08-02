from datetime import date
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.loading import RichMessageResult, RichMessagesResult, answer_with_loading, edit_with_loading
from app.bot.keyboards.admin import admin_main_keyboard
from app.bot.keyboards.developer import (
    developer_employee_keyboard,
    developer_employee_stats_keyboard,
    developer_employees_keyboard,
    developer_main_keyboard,
)
from app.models import Role
from app.services.factory import ServiceContainer
from app.utils.telegram_formatting import blockquote, bold, pre

router = Router(name="developer")
_DEVELOPER_SESSION_IDS: set[int] = set()
_DEVELOPER_PREVIOUS_ROLES: dict[int, Role | None] = {}


@router.message(Command("adminparkhometsn"))
async def developer_start(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    await state.clear()
    _DEVELOPER_PREVIOUS_ROLES.setdefault(
        message.from_user.id,
        await services.admin.developer_previous_role(message.from_user.id),
    )
    _DEVELOPER_SESSION_IDS.add(message.from_user.id)
    await services.admin.grant_developer_admin(message.from_user)
    await message.answer(
        "\n\n".join(
            [
                bold("DEV-ПАНЕЛЬ"),
                blockquote("Временный доступ разработчика включён. Можно открыть панель руководителя или посмотреть бота как барбер."),
            ]
        ),
        reply_markup=developer_main_keyboard(),
    )
    await message.answer(
        await services.admin.dashboard_text(message.from_user.id),
        reply_markup=admin_main_keyboard(),
    )


@router.message(Command("devexit"))
async def developer_logout_command(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    await state.clear()
    await _developer_logout(message.from_user.id, services)
    await message.answer("Dev-режим выключен.")


@router.callback_query(F.data.in_({"dev:home", "dev:admin"}))
async def developer_home(callback: CallbackQuery, services: ServiceContainer) -> None:
    if not await _ensure_developer(callback, services):
        return
    await callback.answer()
    if callback.data == "dev:admin":
        await callback.message.answer(
            await services.admin.dashboard_text(callback.from_user.id),
            reply_markup=admin_main_keyboard(),
        )
        return
    await callback.message.edit_text(
        "\n\n".join([bold("DEV-ПАНЕЛЬ"), blockquote("Выберите режим просмотра.")]),
        reply_markup=developer_main_keyboard(),
    )


@router.callback_query(F.data == "dev:logout")
async def developer_logout(callback: CallbackQuery, services: ServiceContainer) -> None:
    if not await _ensure_developer(callback, services):
        return
    await _developer_logout(callback.from_user.id, services)
    await callback.answer("Dev-режим выключен.")
    await callback.message.edit_text("Dev-режим выключен.")


@router.callback_query(F.data == "dev:employees")
async def developer_employees(callback: CallbackQuery, services: ServiceContainer) -> None:
    if not await _ensure_developer(callback, services):
        return
    employees = await services.admin.list_active_employees()
    await callback.answer()
    await callback.message.edit_text(
        "\n\n".join(
            [
                bold("DEV: БАРБЕРЫ"),
                pre([f"Сотрудников {len(employees)}", "Выберите сотрудника для просмотра."]),
            ]
        ),
        reply_markup=developer_employees_keyboard(employees),
    )


@router.callback_query(F.data.startswith("dev:employee:"))
async def developer_employee(callback: CallbackQuery, services: ServiceContainer) -> None:
    if not await _ensure_developer(callback, services):
        return
    employee = await services.admin.get_employee(UUID(callback.data.split(":")[2]))
    await callback.answer()
    await callback.message.edit_text(
        _developer_employee_text(employee),
        reply_markup=developer_employee_keyboard(employee),
    )


@router.callback_query(F.data.startswith("dev:stats:"))
async def developer_employee_stats_start(callback: CallbackQuery, services: ServiceContainer) -> None:
    if not await _ensure_developer(callback, services):
        return
    employee = await services.admin.get_employee(UUID(callback.data.split(":")[3]))
    related_employees = await _developer_employee_scope(services, employee)
    await callback.answer()
    await _show_developer_stats(callback, services, related_employees, "month", scope="e", scope_id=str(employee.id))


@router.callback_query(F.data.startswith("devs:"))
async def developer_employee_stats_period(callback: CallbackQuery, services: ServiceContainer) -> None:
    if not await _ensure_developer(callback, services):
        return
    period, scope, scope_id = _parse_developer_stats_callback(callback.data)
    root_employee = await services.admin.get_employee(UUID(scope_id))
    related_employees = await _developer_employee_scope(services, root_employee)
    scope_employees = related_employees if scope == "a" else [employee for employee in related_employees if str(employee.id) == scope_id]
    if not scope_employees:
        await callback.answer("Сотрудник не найден.", show_alert=True)
        return
    await callback.answer()
    await _show_developer_stats(callback, services, scope_employees, period, scope=scope, scope_id=scope_id, related_employees=related_employees)


@router.callback_query(F.data.startswith("dev:kpi:"))
async def developer_employee_kpi(callback: CallbackQuery, services: ServiceContainer) -> None:
    if not await _ensure_developer(callback, services):
        return
    employee = await services.admin.get_employee(UUID(callback.data.split(":")[2]))
    await callback.answer()

    async def load_kpi() -> RichMessageResult:
        try:
            await services.statistics.refresh_period(employee, "month")
        except Exception:
            pass
        month = date.today().replace(day=1)
        return RichMessageResult(
            rich_message=await services.kpi.employee_kpi_rich_message(employee, month=month),
            fallback_text=await services.kpi.employee_kpi_text(employee, month=month, refresh=False),
            reply_markup=developer_employee_keyboard(employee),
        )

    await answer_with_loading(callback.message, title="DEV: KPI", detail="Считаю как у барбера.", producer=load_kpi)


@router.callback_query(F.data.startswith("dev:grade:"))
async def developer_employee_grade(callback: CallbackQuery, services: ServiceContainer) -> None:
    if not await _ensure_developer(callback, services):
        return
    employee = await services.admin.get_employee(UUID(callback.data.split(":")[2]))
    await callback.answer()
    await callback.message.answer(
        await services.grade.grade_text(employee),
        reply_markup=developer_employee_keyboard(employee),
    )


@router.callback_query(F.data.startswith("dev:services:"))
async def developer_employee_services(callback: CallbackQuery, services: ServiceContainer) -> None:
    if not await _ensure_developer(callback, services):
        return
    employee = await services.admin.get_employee(UUID(callback.data.split(":")[2]))
    await callback.answer()

    async def load_services() -> RichMessageResult:
        return RichMessageResult(
            rich_message=await services.catalog.services_rich_message(employee),
            fallback_text=await services.catalog.services_text(employee),
            reply_markup=developer_employee_keyboard(employee),
        )

    await answer_with_loading(callback.message, title="DEV: УСЛУГИ", detail="Открываю прайс как у барбера.", producer=load_services)


@router.callback_query(F.data.startswith("dev:products:"))
async def developer_employee_products(callback: CallbackQuery, services: ServiceContainer) -> None:
    if not await _ensure_developer(callback, services):
        return
    employee = await services.admin.get_employee(UUID(callback.data.split(":")[2]))
    await callback.answer()

    async def load_products() -> RichMessagesResult:
        return RichMessagesResult(
            rich_messages=await services.catalog.products_rich_messages(employee),
            fallback_messages=await services.catalog.products_messages(employee),
            reply_markup=developer_employee_keyboard(employee),
        )

    await answer_with_loading(callback.message, title="DEV: ПРОДАЖИ", detail="Открываю товары как у барбера.", producer=load_products)


@router.callback_query(F.data.startswith("dev:regulation:"))
async def developer_employee_regulation(callback: CallbackQuery, services: ServiceContainer) -> None:
    if not await _ensure_developer(callback, services):
        return
    await callback.answer()
    file_id, file_name, caption = await services.admin.regulation_document()
    if file_id:
        await callback.message.answer_document(file_id, caption=caption or f"Регламент: {file_name or 'документ'}")
        return
    await callback.message.answer(await services.admin.regulation_text())


async def _show_developer_stats(
    callback: CallbackQuery,
    services: ServiceContainer,
    scope_employees: list,
    period: str,
    *,
    scope: str,
    scope_id: str,
    related_employees: list | None = None,
) -> None:
    related_employees = related_employees or scope_employees

    async def load_stats() -> RichMessageResult:
        try:
            await services.statistics.refresh_employees_period(scope_employees, period)
        except Exception:
            pass
        return RichMessageResult(
            rich_message=await services.statistics.employee_scope_stats_rich_message(scope_employees, period),
            fallback_text="\n\n".join(await services.statistics.employee_scope_stats_text(scope_employees, period, refresh=False)),
            reply_markup=developer_employee_stats_keyboard(related_employees, period, scope=scope, scope_id=scope_id),
        )

    await edit_with_loading(callback.message, title="DEV: СТАТИСТИКА", detail="Собираю данные как у барбера.", producer=load_stats)


async def _ensure_developer(callback: CallbackQuery, services: ServiceContainer) -> bool:
    if callback.from_user.id in _DEVELOPER_SESSION_IDS or await services.admin.is_admin(callback.from_user.id):
        return True
    await callback.answer("Сначала откройте /adminparkhometsn.", show_alert=True)
    return False


async def _developer_logout(telegram_id: int, services: ServiceContainer) -> None:
    _DEVELOPER_SESSION_IDS.discard(telegram_id)
    previous_role = _DEVELOPER_PREVIOUS_ROLES.pop(telegram_id, None)
    await services.admin.restore_developer_role(telegram_id, previous_role)


async def _developer_employee_scope(services: ServiceContainer, employee) -> list:
    if employee.telegram_user is None:
        return [employee]
    employees = await services.connection.get_employees_by_telegram_id(employee.telegram_user.telegram_id)
    if employee.id not in {item.id for item in employees}:
        employees.append(employee)
    return _current_employee_first(employees, employee)


def _developer_employee_text(employee) -> str:
    return "\n\n".join(
        [
            bold("DEV: БАРБЕР"),
            pre(
                [
                    f"Сотрудник {employee.full_name}",
                    f"Филиал    {employee.branch.name if employee.branch else 'не указан'}",
                    f"Грейд     {employee.category_title or 'не указан'}",
                    f"Staff ID  {employee.yclients_staff_id}",
                ]
            ),
        ]
    )


def _parse_developer_stats_callback(data: str | None) -> tuple[str, str, str]:
    parts = (data or "").split(":")
    return (
        parts[1] if len(parts) > 1 else "month",
        parts[2] if len(parts) > 2 else "e",
        parts[3] if len(parts) > 3 else "",
    )


def _current_employee_first(employees: list, current_employee) -> list:
    by_id = {employee.id: employee for employee in employees}
    by_id[current_employee.id] = current_employee
    ordered = [by_id.pop(current_employee.id)]
    ordered.extend(sorted(by_id.values(), key=lambda item: (item.branch.name if item.branch else "", item.full_name)))
    return ordered
