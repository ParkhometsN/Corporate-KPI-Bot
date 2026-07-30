from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class KpiRule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "kpi_rules"
    __table_args__ = (
        UniqueConstraint("company_id", "threshold_amount", name="uq_kpi_rules_company_threshold"),
    )

    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    threshold_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)

    company = relationship("Company", back_populates="kpi_rules")


class EmployeeKpi(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "employee_kpi"
    __table_args__ = (
        UniqueConstraint("employee_id", "month", name="uq_employee_kpi_employee_month"),
    )

    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    month: Mapped[date] = mapped_column(Date, index=True)
    service_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    additional_services_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    kpi_base_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    earned_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    applies_from_month: Mapped[date] = mapped_column(Date, index=True)
    calculated_at: Mapped[datetime] = mapped_column(nullable=False)

    employee = relationship("Employee", back_populates="employee_kpi")


class GradeRule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "grade_rules"
    __table_args__ = (
        UniqueConstraint("company_id", "category_title", name="uq_grade_rules_company_category"),
    )

    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    category_title: Mapped[str] = mapped_column(String(64), nullable=False)
    base_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    average_daily_revenue_required: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    months_required: Mapped[int] = mapped_column(nullable=False)
    minimum_employment_months: Mapped[int] = mapped_column(nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    company = relationship("Company", back_populates="grade_rules")

