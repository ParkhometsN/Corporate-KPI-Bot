from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.models import NotificationSettings


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


def stats_period_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сегодня", callback_data="empstats:today"),
                InlineKeyboardButton(text="Неделя", callback_data="empstats:week"),
                InlineKeyboardButton(text="Месяц", callback_data="empstats:month"),
            ]
        ]
    )


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
