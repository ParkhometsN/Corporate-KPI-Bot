from datetime import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.models import NotificationSettings, TelegramUser
from app.utils.telegram_formatting import blockquote, bold, pre
from app.utils.exceptions import EntityNotFoundError


class NotificationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def get_or_create(self, telegram_user: TelegramUser) -> NotificationSettings:
        result = await self._session.execute(
            select(NotificationSettings).where(NotificationSettings.telegram_user_id == telegram_user.id)
        )
        settings = result.scalar_one_or_none()
        if settings is None:
            settings = NotificationSettings(telegram_user_id=telegram_user.id)
            self._session.add(settings)
            await self._session.flush()
        return settings

    async def toggle(self, telegram_user: TelegramUser, field_name: str) -> NotificationSettings:
        settings = await self.get_or_create(telegram_user)
        if not hasattr(settings, field_name):
            raise EntityNotFoundError("Настройка уведомлений не найдена.")
        setattr(settings, field_name, not getattr(settings, field_name))
        await self._session.flush()
        return settings

    async def set_time(self, telegram_user: TelegramUser, value: time) -> NotificationSettings:
        settings = await self.get_or_create(telegram_user)
        settings.notification_time = value
        await self._session.flush()
        return settings

    async def settings_text(self, telegram_user: TelegramUser) -> str:
        settings = await self.get_or_create(telegram_user)
        rows = [
            _setting_row("Ежедневные отчёты", settings.daily_enabled),
            _setting_row("Еженедельные отчёты", settings.weekly_enabled),
            _setting_row("Ежемесячные отчёты", settings.monthly_enabled),
            _setting_row("KPI-напоминания", settings.kpi_reminders_enabled),
            _setting_row("Grade-уведомления", settings.grade_notifications_enabled),
            _setting_row("Обновления цен", settings.price_updates_enabled),
            _setting_row("Обновления товаров", settings.product_updates_enabled),
            f"Время отправки       {settings.notification_time:%H:%M}",
        ]
        return "\n\n".join(
            [
                bold("НАСТРОЙКИ УВЕДОМЛЕНИЙ"),
                pre(rows),
                blockquote("Нажмите на пункт ниже, чтобы переключить уведомление."),
            ]
        )


def _setting_row(title: str, enabled: bool) -> str:
    marker = "✅" if enabled else "❌"
    return f"{marker} {title:<22} {'включено' if enabled else 'выключено'}"
