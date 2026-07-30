from datetime import time
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class NotificationSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notifications"

    telegram_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    daily_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    weekly_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    monthly_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    kpi_reminders_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    grade_notifications_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    price_updates_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    product_updates_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    notification_time: Mapped[time] = mapped_column(default=time(10, 0), nullable=False)

    telegram_user = relationship("TelegramUser", back_populates="notifications")

