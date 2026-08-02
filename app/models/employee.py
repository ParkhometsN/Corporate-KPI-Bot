from datetime import date, datetime
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Employee(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("branch_id", "yclients_staff_id", name="uq_employees_branch_staff"),
    )

    branch_id: Mapped[UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    yclients_staff_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    specialization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_title: Mapped[str | None] = mapped_column(String(64), nullable=True)
    employment_started_at: Mapped[date | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    connected_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)

    branch = relationship("Branch", back_populates="employees")
    telegram_user = relationship("TelegramUser", back_populates="employees")
    connection_codes = relationship("ConnectionCode", back_populates="employee", cascade="all, delete-orphan")
    daily_statistics = relationship("DailyStatistic", back_populates="employee", cascade="all, delete-orphan")
    monthly_statistics = relationship("MonthlyStatistic", back_populates="employee", cascade="all, delete-orphan")
    employee_kpi = relationship("EmployeeKpi", back_populates="employee", cascade="all, delete-orphan")
