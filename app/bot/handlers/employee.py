from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.loading import RichMessageResult, answer_with_loading, edit_with_loading
from app.bot.keyboards.employee import (
    employee_main_keyboard,
    notification_settings_keyboard,
    stats_period_keyboard,
)
from app.services.factory import ServiceContainer
from app.utils.exceptions import AccessDeniedError

router = Router(name="employee")


@router.message(F.text.in_({"Статистика", "📊 Статистика"}))
async def employee_statistics(message: Message, services: ServiceContainer) -> None:
    employee = await _require_employee(message, services)
    await answer_with_loading(
        message,
        title="ЗАГРУЗКА СТАТИСТИКИ",
        detail="Запрашиваю YCLIENTS и собираю период.",
        producer=lambda: services.statistics.employee_stats_text(employee, "month"),
        reply_markup=stats_period_keyboard(),
    )


@router.callback_query(F.data.startswith("empstats:"))
async def employee_statistics_period(callback: CallbackQuery, services: ServiceContainer) -> None:
    employee = await services.connection.get_employee_by_telegram_id(callback.from_user.id)
    if employee is None:
        await callback.answer("Сначала подключитесь через /start.", show_alert=True)
        return
    period = callback.data.split(":", maxsplit=1)[1]
    await callback.answer()
    await edit_with_loading(
        callback.message,
        title="ЗАГРУЗКА СТАТИСТИКИ",
        detail="Обновляю выбранный период.",
        producer=lambda: services.statistics.employee_stats_text(employee, period),
        reply_markup=stats_period_keyboard(),
    )


@router.message(F.text.in_({"KPI", "🎯 KPI"}))
async def employee_kpi(message: Message, services: ServiceContainer) -> None:
    employee = await _require_employee(message, services)
    await answer_with_loading(
        message,
        title="ЗАГРУЗКА KPI",
        detail="Обновляю месяц и пересчитываю процент.",
        producer=lambda: services.kpi.employee_kpi_text(employee),
    )


@router.message(F.text.in_({"Grade Up", "📈 Grade Up"}))
async def employee_grade(message: Message, services: ServiceContainer) -> None:
    employee = await _require_employee(message, services)
    await answer_with_loading(
        message,
        title="ЗАГРУЗКА GRADE UP",
        detail="Считаю прогресс до следующей категории.",
        producer=lambda: services.grade.grade_text(employee),
    )


@router.message(F.text.in_({"Услуги", "💇 Услуги"}))
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


@router.message(F.text.in_({"Товары", "🧴 Товары"}))
async def employee_products(message: Message, services: ServiceContainer) -> None:
    employee = await _require_employee(message, services)
    await answer_with_loading(
        message,
        title="ЗАГРУЗКА ТОВАРОВ",
        detail="Запрашиваю товары напрямую из YCLIENTS API.",
        producer=lambda: services.catalog.products_text(employee),
    )


@router.message(F.text.in_({"Регламент", "📋 Регламент"}))
async def employee_regulation(message: Message, services: ServiceContainer) -> None:
    await _require_employee(message, services)
    await message.answer(await services.admin.regulation_text())


@router.message(F.text.in_({"Настройки", "⚙ Настройки"}))
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
