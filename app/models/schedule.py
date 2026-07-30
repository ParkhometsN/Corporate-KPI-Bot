from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Schedule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "schedules"
    __table_args__ = (UniqueConstraint("job_id", name="uq_schedules_job_id"),)

    job_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    interval_minutes: Mapped[int | None] = mapped_column(nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
