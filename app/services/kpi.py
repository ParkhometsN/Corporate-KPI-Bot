from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.config.settings import Settings
from app.models import Employee, EmployeeKpi
from app.repositories import CompanyRepository, EmployeeKpiRepository, KpiRuleRepository, MonthlyStatisticRepository
from app.services.statistics import StatisticsService, money
from app.utils.exceptions import AppError
from app.utils.rich_messages import key_value_rows, paragraph, rich_message, table, table_rows
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
        kpi_base = _kpi_bonus_base(monthly_stat)
        earned_percent = _earned_percent_from_rules(rules, kpi_base)
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
        if refresh:
            try:
                await self._statistics.refresh_period(employee, "month")
            except AppError as exc:
                logger.warning(
                    "employee_kpi_refresh_app_error",
                    employee_id=str(employee.id),
                    month=month.isoformat(),
                    error=exc.public_message[:200],
                )
            except Exception as exc:
                logger.exception("employee_kpi_refresh_failed", employee_id=str(employee.id), month=month.isoformat())
        entity = await self.calculate_employee_month(employee, month)
        if entity is None:
            return (
                f"{bold('KPI')}\n\n"
                f"{blockquote('Компания не настроена, поэтому правила KPI недоступны.')}"
            )
        monthly_stat = await self._monthly_stats.get_for_employee(employee.id, month)
        goal_amount = await self._next_kpi_goal(entity.kpi_base_amount)
        goal_percent = await self._kpi_goal_percent(goal_amount)
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
            *_month_period_lines(entity.month),
            f"Сотрудник   {employee.full_name}",
            f"Грейд       {employee.category_title or 'не указан'}",
            f"Основные    {money(entity.service_revenue)}",
            f"Доп. услуги {money(entity.additional_services_revenue)}",
            f"Товары      {monthly_stat.products_sold if monthly_stat else 0} / {money(monthly_stat.products_revenue if monthly_stat else Decimal('0'))}",
            f"KPI база    {money(entity.kpi_base_amount)}",
            f"Бонус       +{entity.earned_percent.quantize(Decimal('0.01'))}%",
            f"Применится  {entity.applies_from_month:%m.%Y}",
        ]
        progress = [
            f"Цель        {_kpi_goal_line(goal_amount, goal_percent)}",
            f"До цели     {money(amount_left) if amount_left is not None else 'не задано'}",
            f"Прогресс    {progress_bar(goal_progress)} {goal_progress:.0f}%",
        ]
        parts = [
            bold("KPI"),
            pre(summary),
            pre(progress),
            blockquote(_kpi_comment_lines()),
        ]
        return "\n\n".join(parts)

    async def employee_kpi_rich_message(
        self,
        employee: Employee,
        month: date | None = None,
    ) -> object:
        month = (month or date.today()).replace(day=1)
        entity = await self.calculate_employee_month(employee, month)
        if entity is None:
            return rich_message("KPI", paragraph("Компания не настроена, поэтому правила KPI недоступны."))
        monthly_stat = await self._monthly_stats.get_for_employee(employee.id, month)
        goal_amount = await self._next_kpi_goal(entity.kpi_base_amount)
        goal_percent = await self._kpi_goal_percent(goal_amount)
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
        return rich_message(
            "KPI",
            table(
                key_value_rows(
                    [
                        ("Период", f"{entity.month:%m.%Y}"),
                        ("Даты", _month_period_values(entity.month)["dates"]),
                        ("Сотрудник", employee.full_name),
                        ("Филиал", employee.branch.name if employee.branch else "не указан"),
                        ("Грейд", employee.category_title or "не указан"),
                    ]
                )
            ),
            table(
                key_value_rows(
                    [
                        ("Основные услуги", money(entity.service_revenue)),
                        ("Доп. услуги", money(entity.additional_services_revenue)),
                        ("Товары", f"{monthly_stat.products_sold if monthly_stat else 0} / {money(monthly_stat.products_revenue if monthly_stat else Decimal('0'))}"),
                        ("KPI база", money(entity.kpi_base_amount)),
                        ("Бонус", f"+{entity.earned_percent.quantize(Decimal('0.01'))}%"),
                        ("Применится", f"{entity.applies_from_month:%m.%Y}"),
                    ]
                )
            ),
            table(
                key_value_rows(
                    [
                        ("Цель", _kpi_goal_line(goal_amount, goal_percent)),
                        ("До цели", money(amount_left) if amount_left is not None else "не задано"),
                        ("Прогресс", f"{progress_bar(goal_progress)} {goal_progress:.0f}%"),
                    ]
                )
            ),
            paragraph("KPI база считается как дополнительные услуги + товары. Процент переносится на следующий месяц."),
        )

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
        total_base = Decimal("0")
        if refresh:
            try:
                await self._statistics.refresh_team_period(employees, "month")
            except AppError as exc:
                logger.warning(
                    "team_kpi_refresh_app_error",
                    title=title,
                    month=month.isoformat(),
                    employees=len(employees),
                    error=exc.public_message[:200],
                )
            except Exception as exc:
                logger.exception("team_kpi_refresh_failed", title=title, month=month.isoformat())
        for employee in employees:
            entity = await self.calculate_employee_month(employee, month)
            if entity is None:
                continue
            total_base += entity.kpi_base_amount
            rows.append((employee, entity))

        table = [f"{'Сотрудник':18} {'KPI база':>11} {'Бонус':>7} {'с':>7}"]
        for employee, entity in sorted(rows, key=lambda item: item[1].kpi_base_amount, reverse=True):
            table.append(
                f"{employee.full_name[:18]:18} "
                f"{money(entity.kpi_base_amount):>11} "
                f"+{entity.earned_percent.quantize(Decimal('0.01')):>5}% "
                f"{entity.applies_from_month:%m.%Y}"
            )

        parts = [
            bold("KPI КОМАНДЫ"),
            pre(
                [
                    f"Группа       {title}",
                    f"Период      {month:%m.%Y}",
                    *_month_period_lines(month),
                    f"Сотрудников {len(employees)}",
                    f"База KPI    {money(total_base)}",
                ]
            ),
            pre(table),
            blockquote(_kpi_comment_lines()),
        ]
        return "\n\n".join(parts)

    async def team_kpi_rich_message(
        self,
        employees: list[Employee],
        *,
        title: str,
        month: date | None = None,
    ) -> object:
        month = (month or date.today()).replace(day=1)
        if not employees:
            return rich_message("KPI КОМАНДЫ", paragraph("Сотрудники пока не синхронизированы."))

        rows = []
        total_base = Decimal("0")
        for employee in employees:
            entity = await self.calculate_employee_month(employee, month)
            if entity is None:
                continue
            total_base += entity.kpi_base_amount
            rows.append((employee, entity))
        employee_rows = [
            [
                employee.branch.name if employee.branch else "не указан",
                employee.full_name,
                money(entity.kpi_base_amount),
                f"+{entity.earned_percent.quantize(Decimal('0.01'))}%",
                f"{entity.applies_from_month:%m.%Y}",
            ]
            for employee, entity in sorted(rows, key=lambda item: item[1].kpi_base_amount, reverse=True)
        ]
        return rich_message(
            "KPI КОМАНДЫ",
            table(
                key_value_rows(
                    [
                        ("Группа", title),
                        ("Период", f"{month:%m.%Y}"),
                        ("Даты", _month_period_values(month)["dates"]),
                        ("Сотрудников", len(employees)),
                        ("База KPI", money(total_base)),
                    ]
                )
            ),
            table(
                table_rows(
                    ["Филиал", "Сотрудник", "KPI база", "Бонус", "С"],
                    employee_rows,
                    numeric_columns={2, 3},
                )
            ),
            paragraph("KPI база считается как дополнительные услуги + товары. Процент переносится на следующий месяц."),
        )

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

    async def _kpi_goal_percent(self, goal_amount: Decimal | None) -> Decimal | None:
        if goal_amount is None:
            return None
        company = await self._companies.get_default()
        if company is None:
            return None
        for rule in await self._kpi_rules.list_active(company.id):
            if rule.threshold_amount == goal_amount:
                return rule.percent
        return None


def _next_month(month: date) -> date:
    if month.month == 12:
        return date(month.year + 1, 1, 1)
    return date(month.year, month.month + 1, 1)


def _month_period_lines(month: date) -> list[str]:
    values = _month_period_values(month)
    return [f"Даты        {values['dates']}"]


def _month_period_values(month: date) -> dict[str, str]:
    start = month.replace(day=1)
    today = date.today()
    if start.year == today.year and start.month == today.month:
        end = today
    else:
        end = _next_month(start) - date.resolution
    return {"dates": _date_range_label(start, end)}


def _date_range_label(start: date, end: date) -> str:
    if start == end:
        return f"{start:%d.%m.%Y}"
    if start.year == end.year:
        return f"{start:%d.%m}-{end:%d.%m.%Y}"
    return f"{start:%d.%m.%Y}-{end:%d.%m.%Y}"


def _kpi_bonus_base(monthly_stat) -> Decimal:
    return monthly_stat.additional_services_revenue + monthly_stat.products_revenue


def _earned_percent_from_rules(rules, kpi_base: Decimal) -> Decimal:
    earned_percent = Decimal("0")
    for rule in rules:
        if kpi_base >= rule.threshold_amount:
            earned_percent = rule.percent
    return earned_percent


def _kpi_goal_line(goal_amount: Decimal | None, goal_percent: Decimal | None) -> str:
    if goal_amount is None:
        return "не задана"
    if goal_percent is None:
        return money(goal_amount)
    return f"{money(goal_amount)} для +{goal_percent.quantize(Decimal('0.01'))}%"


def _kpi_comment_lines() -> list[str]:
    return [
        "KPI база считается как дополнительные услуги + товары.",
        "Порог 37 000 ₽ даёт +2%, порог 60 000 ₽ даёт +5% к проценту от услуг.",
        "Процент не применяется сразу: он переносится на следующий месяц после закрытия текущего.",
    ]
