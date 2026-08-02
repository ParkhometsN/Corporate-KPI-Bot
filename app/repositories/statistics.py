from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import extract, select

from app.models import DailyStatistic, EmployeeKpi, MonthlyStatistic
from app.repositories.base import BaseRepository


class DailyStatisticRepository(BaseRepository[DailyStatistic]):
    model = DailyStatistic

    async def get_for_employee(self, employee_id: UUID, day: date) -> DailyStatistic | None:
        result = await self.session.execute(
            select(DailyStatistic).where(
                DailyStatistic.employee_id == employee_id,
                DailyStatistic.statistic_date == day,
            )
        )
        return result.scalar_one_or_none()

    async def list_period(self, employee_id: UUID, date_from: date, date_to: date) -> list[DailyStatistic]:
        result = await self.session.execute(
            select(DailyStatistic)
            .where(
                DailyStatistic.employee_id == employee_id,
                DailyStatistic.statistic_date >= date_from,
                DailyStatistic.statistic_date <= date_to,
            )
            .order_by(DailyStatistic.statistic_date.asc())
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        employee_id: UUID,
        statistic_date: date,
        haircuts_count: int,
        service_revenue: Decimal,
        additional_services_revenue: Decimal,
        total_revenue: Decimal,
        average_check: Decimal,
        attendance_percent: Decimal,
        client_records_count: int,
        returning_clients_count: int,
        returning_clients_percent: Decimal,
        occupancy_percent: Decimal,
        products_sold: int,
        products_revenue: Decimal,
    ) -> DailyStatistic:
        stat = await self.get_for_employee(employee_id, statistic_date)
        if stat is None:
            stat = DailyStatistic(employee_id=employee_id, statistic_date=statistic_date)
            self.session.add(stat)
        stat.haircuts_count = haircuts_count
        stat.service_revenue = service_revenue
        stat.additional_services_revenue = additional_services_revenue
        stat.total_revenue = total_revenue
        stat.average_check = average_check
        stat.attendance_percent = attendance_percent
        stat.client_records_count = client_records_count
        stat.returning_clients_count = returning_clients_count
        stat.returning_clients_percent = returning_clients_percent
        stat.occupancy_percent = occupancy_percent
        stat.products_sold = products_sold
        stat.products_revenue = products_revenue
        await self.session.flush()
        return stat


class MonthlyStatisticRepository(BaseRepository[MonthlyStatistic]):
    model = MonthlyStatistic

    async def get_for_employee(self, employee_id: UUID, month: date) -> MonthlyStatistic | None:
        result = await self.session.execute(
            select(MonthlyStatistic).where(
                MonthlyStatistic.employee_id == employee_id,
                MonthlyStatistic.month == month,
            )
        )
        return result.scalar_one_or_none()

    async def latest_for_employee(self, employee_id: UUID) -> MonthlyStatistic | None:
        result = await self.session.execute(
            select(MonthlyStatistic)
            .where(MonthlyStatistic.employee_id == employee_id)
            .order_by(MonthlyStatistic.month.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def upsert_from_daily(self, employee_id: UUID, month: date) -> MonthlyStatistic:
        result = await self.session.execute(
            select(DailyStatistic).where(
                DailyStatistic.employee_id == employee_id,
                extract("year", DailyStatistic.statistic_date) == month.year,
                extract("month", DailyStatistic.statistic_date) == month.month,
            )
        )
        daily_stats = list(result.scalars().all())
        stat = await self.get_for_employee(employee_id, month)
        if stat is None:
            stat = MonthlyStatistic(employee_id=employee_id, month=month)
            self.session.add(stat)
        stat.haircuts_count = sum(item.haircuts_count for item in daily_stats)
        stat.service_revenue = sum((item.service_revenue for item in daily_stats), Decimal("0"))
        stat.additional_services_revenue = sum(
            (item.additional_services_revenue for item in daily_stats), Decimal("0")
        )
        stat.total_revenue = sum((item.total_revenue for item in daily_stats), Decimal("0"))
        stat.products_sold = sum(item.products_sold for item in daily_stats)
        stat.products_revenue = sum((item.products_revenue for item in daily_stats), Decimal("0"))
        stat.average_check = (
            stat.total_revenue / stat.haircuts_count if stat.haircuts_count else Decimal("0")
        )
        stat.attendance_percent = (
            sum((item.attendance_percent for item in daily_stats), Decimal("0")) / len(daily_stats)
            if daily_stats
            else Decimal("0")
        )
        stat.client_records_count = sum(item.client_records_count for item in daily_stats)
        stat.returning_clients_count = sum(item.returning_clients_count for item in daily_stats)
        stat.returning_clients_percent = _percent(
            stat.returning_clients_count,
            stat.client_records_count,
        )
        stat.occupancy_percent = (
            sum((item.occupancy_percent for item in daily_stats), Decimal("0")) / len(daily_stats)
            if daily_stats
            else Decimal("0")
        )
        await self.session.flush()
        return stat


def _percent(value: int, total: int) -> Decimal:
    if total <= 0:
        return Decimal("0")
    return Decimal(value) / Decimal(total) * Decimal("100")


class EmployeeKpiRepository(BaseRepository[EmployeeKpi]):
    model = EmployeeKpi

    async def get_for_employee(self, employee_id: UUID, month: date) -> EmployeeKpi | None:
        result = await self.session.execute(
            select(EmployeeKpi).where(EmployeeKpi.employee_id == employee_id, EmployeeKpi.month == month)
        )
        return result.scalar_one_or_none()
