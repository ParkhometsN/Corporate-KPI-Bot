from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.models import NotificationSettings
from app.services.statistics import canonical_period, period_kind, shifted_period


def employee_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Статистика"), KeyboardButton(text="KPI")],
            [KeyboardButton(text="Grade Up"), KeyboardButton(text="Услуги")],
            [KeyboardButton(text="Товары"), KeyboardButton(text="Регламент")],
            [KeyboardButton(text="Настройки")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите раздел",
    )


def stats_period_keyboard(selected_period: str = "month") -> InlineKeyboardMarkup:
    current = canonical_period(selected_period)
    kind = period_kind(current)

    def marker(expected_kind: str) -> str:
        return "✅ " if kind == expected_kind else ""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="‹", callback_data=f"empstats:{shifted_period(current, -1)}"),
                InlineKeyboardButton(text="Обновить", callback_data=f"empstats:{current}"),
                InlineKeyboardButton(text="›", callback_data=f"empstats:{shifted_period(current, 1)}"),
            ],
            [
                InlineKeyboardButton(text=f"{marker('day')}День", callback_data="empstats:today"),
                InlineKeyboardButton(text=f"{marker('week')}Неделя", callback_data="empstats:week"),
                InlineKeyboardButton(text=f"{marker('month')}Месяц", callback_data="empstats:month"),
            ],
        ]
    )


def kpi_month_keyboard(selected_period: str = "month") -> InlineKeyboardMarkup:
    current = _month_period(selected_period)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="‹", callback_data=f"empkpi:{shifted_period(current, -1)}"),
                InlineKeyboardButton(text="Обновить", callback_data=f"empkpi:{current}"),
                InlineKeyboardButton(text="›", callback_data=f"empkpi:{shifted_period(current, 1)}"),
            ],
        ]
    )


def _month_period(selected_period: str) -> str:
    current = canonical_period(selected_period)
    return current if current.startswith("m") else canonical_period("month")


def notification_settings_keyboard(settings: NotificationSettings | None = None) -> InlineKeyboardMarkup:
    def label(title: str, field_name: str) -> str:
        if settings is None:
            return title
        return f"{'✅' if getattr(settings, field_name) else '❌'} {title}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label("Ежедневные", "daily_enabled"), callback_data="notify:daily_enabled")],
            [InlineKeyboardButton(text=label("Еженедельные", "weekly_enabled"), callback_data="notify:weekly_enabled")],
            [InlineKeyboardButton(text=label("Ежемесячные", "monthly_enabled"), callback_data="notify:monthly_enabled")],
            [InlineKeyboardButton(text=label("KPI-напоминания", "kpi_reminders_enabled"), callback_data="notify:kpi_reminders_enabled")],
            [InlineKeyboardButton(text=label("Grade-уведомления", "grade_notifications_enabled"), callback_data="notify:grade_notifications_enabled")],
            [InlineKeyboardButton(text=label("Обновления цен", "price_updates_enabled"), callback_data="notify:price_updates_enabled")],
            [InlineKeyboardButton(text=label("Обновления товаров", "product_updates_enabled"), callback_data="notify:product_updates_enabled")],
        ]
    )
