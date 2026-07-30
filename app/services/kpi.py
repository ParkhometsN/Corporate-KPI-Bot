from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.config.settings import Settings
from app.models import Employee, EmployeeKpi
from app.repositories import CompanyRepository, EmployeeKpiRepository, KpiRuleRepository, MonthlyStatisticRepository
from app.services.statistics import StatisticsService, money, yclients_data_error_hint
from app.utils.exceptions import AppError
from app.utils.telegram_formatting import blockquote, bold, pre, progress_bar
from app.utils.datetime import utc_now_naive

logger = get_logger(__name__)


class KpiService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._companies = CompanyRepository(session)
        self._kpi_rules = KpiRuleRepository(session)
        self._monthly_stats = MonthlyStatisticRepository(session)
        self._employee_kpi = EmployeeKpiRepository(session)
        self._statistics = StatisticsService(session, settings)

    async def calculate_employee_month(self, employee: Employee, month: date) -> EmployeeKpi | None:
        company = await self._companies.get_default()
        if company is None:
            return None
        month = month.replace(day=1)
        monthly_stat = await self._monthly_stats.upsert_from_daily(employee.id, month)
        rules = await self._kpi_rules.list_active(company.id)
        kpi_base = monthly_stat.service_revenue + monthly_stat.additional_services_revenue
        earned_percent = Decimal("0")
        for rule in rules:
            if kpi_base >= rule.threshold_amount:
                earned_percent = rule.percent
        applies_from_month = _next_month(month)
        entity = await self._employee_kpi.get_for_employee(employee.id, month)
        if entity is None:
            entity = EmployeeKpi(employee_id=employee.id, month=month, applies_from_month=applies_from_month)
            self._employee_kpi.session.add(entity)
        entity.service_revenue = monthly_stat.service_revenue
        entity.additional_services_revenue = monthly_stat.additional_services_revenue
        entity.kpi_base_amount = kpi_base
        entity.earned_percent = earned_percent
        entity.applies_from_month = applies_from_month
        entity.calculated_at = utc_now_naive()
        await self._employee_kpi.session.flush()
        return entity

    async def employee_kpi_text(
        self,
        employee: Employee,
        month: date | None = None,
        *,
        refresh: bool = True,
    ) -> str:
        month = (month or date.today()).replace(day=1)
        refresh_warning: str | None = None
        if refresh:
            try:
                await self._statistics.refresh_period(employee, "month")
            except AppError as exc:
                refresh_warning = yclients_data_error_hint(exc.public_message)
            except Exception as exc:
                logger.exception("employee_kpi_refresh_failed", employee_id=str(employee.id), month=month.isoformat())
                refresh_warning = yclients_data_error_hint(f"Не удалось обновить данные из YCLIENTS: {str(exc)[:200]}")
        entity = await self.calculate_employee_month(employee, month)
        if entity is None:
            return (
                f"{bold('KPI')}\n\n"
                f"{blockquote('ДАЙДЖЕСТ KPI: компания не настроена, поэтому правила KPI недоступны.')}"
            )
        monthly_stat = await self._monthly_stats.get_for_employee(employee.id, month)
        goal_amount = await self._next_kpi_goal(entity.kpi_base_amount)
        goal_progress = (
            min(Decimal("100"), entity.kpi_base_amount / goal_amount * Decimal("100"))
            if goal_amount and goal_amount > 0
            else Decimal("0")
        )
        amount_left = (
            max(Decimal("0"), goal_amount - entity.kpi_base_amount)
            if goal_amount is not None
            else None
        )
        summary = [
            f"Период      {entity.month:%m.%Y}",
            f"Сотрудник   {employee.full_name}",
            f"Грейд       {employee.category_title or 'не указан'}",
            f"База KPI    {money(entity.kpi_base_amount)}",
            f"Процент     {entity.earned_percent.quantize(Decimal('0.01'))}%",
            f"Применится  {entity.applies_from_month:%m.%Y}",
        ]
        progress = [
            f"Цель        {money(goal_amount) if goal_amount else 'не задана'}",
            f"До цели     {money(amount_left) if amount_left is not None else 'не задано'}",
            f"Прогресс    {progress_bar(goal_progress)} {goal_progress:.0f}%",
        ]
        digest = _kpi_digest(
            entity=entity,
            daily_rows=monthly_stat.haircuts_count if monthly_stat else 0,
            refresh_warning=refresh_warning,
        )
        parts = [
            bold("KPI"),
            pre(summary),
            pre(progress),
            blockquote(digest),
        ]
        return "\n\n".join(parts)

    async def team_kpi_text(
        self,
        employees: list[Employee],
        *,
        title: str,
        month: date | None = None,
        refresh: bool = True,
    ) -> str:
        month = (month or date.today()).replace(day=1)
        if not employees:
            return "\n\n".join([bold("KPI КОМАНДЫ"), blockquote("Сотрудники пока не синхронизированы.")])

        rows = []
        refresh_errors = 0
        first_refresh_warning: str | None = None
        total_base = Decimal("0")
        for employee in employees:
            if refresh:
                try:
                    await self._statistics.refresh_period(employee, "month")
                except AppError as exc:
                    refresh_errors += 1
                    if first_refresh_warning is None:
                        first_refresh_warning = yclients_data_error_hint(exc.public_message)
                except Exception as exc:
                    refresh_errors += 1
                    if first_refresh_warning is None:
                        first_refresh_warning = yclients_data_error_hint(
                            f"Не удалось обновить данные из YCLIENTS: {str(exc)[:200]}"
                        )
            entity = await self.calculate_employee_month(employee, month)
            if entity is None:
                continue
            total_base += entity.kpi_base_amount
            rows.append((employee, entity))

        table = [f"{'Сотрудник':18} {'KPI база':>11} {'%':>6} {'с':>7}"]
        for employee, entity in sorted(rows, key=lambda item: item[1].kpi_base_amount, reverse=True):
            table.append(
                f"{employee.full_name[:18]:18} "
                f"{money(entity.kpi_base_amount):>11} "
                f"{entity.earned_percent.quantize(Decimal('0.01')):>6}% "
                f"{entity.applies_from_month:%m.%Y}"
            )

        digest = [
            "KPI база считается как услуги + дополнительные услуги. Товары в KPI сейчас не входят.",
            "Процент применяется со следующего месяца после закрытия текущего.",
        ]
        if first_refresh_warning:
            digest.append(first_refresh_warning)
        digest.append(f"Ошибок обновления: {refresh_errors}" if refresh_errors else "Данные обновлены без ошибок.")

        parts = [
            bold("KPI КОМАНДЫ"),
            pre(
                [
                    f"Группа       {title}",
                    f"Период      {month:%m.%Y}",
                    f"Сотрудников {len(employees)}",
                    f"База KPI    {money(total_base)}",
                ]
            ),
            pre(table),
            blockquote(digest),
        ]
        return "\n\n".join(parts)

    async def _next_kpi_goal(self, kpi_base: Decimal) -> Decimal | None:
        company = await self._companies.get_default()
        if company is None:
            return None
        rules = await self._kpi_rules.list_active(company.id)
        paid_thresholds = [rule.threshold_amount for rule in rules if rule.threshold_amount > 0]
        if not paid_thresholds:
            return None
        for threshold in paid_thresholds:
            if kpi_base < threshold:
                return threshold
        return paid_thresholds[-1]


def _next_month(month: date) -> date:
    if month.month == 12:
        return date(month.year + 1, 1, 1)
    return date(month.year, month.month + 1, 1)


def _kpi_digest(
    *,
    entity: EmployeeKpi,
    daily_rows: int,
    refresh_warning: str | None,
) -> list[str]:
    digest = [
        "KPI база считается как услуги + дополнительные услуги. Товары в KPI сейчас не входят.",
        "Процент не применяется сразу: он переносится на следующий месяц после закрытия текущего.",
    ]
    if refresh_warning:
        digest.insert(0, f"ДАЙДЖЕСТ KPI: свежие данные не подтянулись: {refresh_warning}")
    elif entity.kpi_base_amount == 0:
        if daily_rows == 0:
            digest.insert(0, "ДАЙДЖЕСТ KPI: за месяц нет посещений в дневной статистике.")
        else:
            digest.insert(0, "ДАЙДЖЕСТ KPI: записи есть, но сумма услуг и доп. услуг равна 0 ₽.")
    return digest
