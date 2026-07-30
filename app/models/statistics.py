from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, ForeignKey, JSON, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Statistic(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "statistics"

    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    period_start: Mapped[datetime] = mapped_column(index=True)
    period_end: Mapped[datetime] = mapped_column(index=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class DailyStatistic(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "daily_statistics"
    __table_args__ = (
        UniqueConstraint("employee_id", "statistic_date", name="uq_daily_statistics_employee_date"),
    )

    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    statistic_date: Mapped[date] = mapped_column(Date, index=True)
    haircuts_count: Mapped[int] = mapped_column(default=0, nullable=False)
    service_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    additional_services_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    total_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    average_check: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    attendance_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    products_sold: Mapped[int] = mapped_column(default=0, nullable=False)
    products_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    employee = relationship("Employee", back_populates="daily_statistics")


class MonthlyStatistic(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "monthly_statistics"
    __table_args__ = (
        UniqueConstraint("employee_id", "month", name="uq_monthly_statistics_employee_month"),
    )

    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    month: Mapped[date] = mapped_column(Date, index=True)
    haircuts_count: Mapped[int] = mapped_column(default=0, nullable=False)
    service_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    additional_services_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    total_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    average_check: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    attendance_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    products_sold: Mapped[int] = mapped_column(default=0, nullable=False)
    products_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    employee = relationship("Employee", back_populates="monthly_statistics")

