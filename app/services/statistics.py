from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.config.settings import Settings
from app.models import Branch, Company, Employee
from app.repositories import CompanyRepository, DailyStatisticRepository, FranchiseeRepository, KpiRuleRepository
from app.services.security import EncryptionService
from app.utils.exceptions import AppError
from app.utils.rich_messages import cell, key_value_rows, paragraph, rich_message, table, table_rows
from app.utils.telegram_formatting import blockquote, bold, money as format_money, pre, progress_bar, shorten
from app.yclients.client import (
    YClientsApiError,
    YClientsClient,
    _calculate_daily_statistic,
    _record_staff_id,
    _record_statistic_date,
)
from app.yclients.types import YClientsDailyStatistic

logger = get_logger(__name__)
_REFRESH_CACHE: dict[tuple[str, str, str, date, date], float] = {}
_MONTH_NAMES = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


class StatisticsService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._companies = CompanyRepository(session)
        self._daily_stats = DailyStatisticRepository(session)
        self._franchisees = FranchiseeRepository(session)
        self._kpi_rules = KpiRuleRepository(session)
        self._encryption = EncryptionService(settings)

    async def sync_employee_day(self, employee: Employee, statistic_date: date) -> YClientsDailyStatistic | None:
        company = await self._companies.get_default()
        if company is None:
            return None
        branch = employee.branch
        if branch is None:
            return None
        client = await self._client_for_branch(company, branch)
        remote_stat = await client.get_daily_statistics(
            company_id=branch.yclients_branch_id,
            employee_staff_id=employee.yclients_staff_id,
            statistic_date=statistic_date,
        )
        await self._upsert_daily_stat(employee, remote_stat)
        return remote_stat

    async def sync_branch_period(
        self,
        branch: Branch,
        employees: list[Employee],
        date_from: date,
        date_to: date,
    ) -> list[YClientsDailyStatistic]:
        company = await self._companies.get_default()
        if company is None:
            return []
        client = await self._client_for_branch(company, branch)
        records = await client.list_records(
            company_id=branch.yclients_branch_id,
            date_from=date_from,
            date_to=date_to,
        )
        records_by_day = _records_by_day(records, date_from=date_from, date_to=date_to)
        visible_staff_ids = {
            staff_id
            for staff_id in (_record_staff_id(record) for record in records)
            if staff_id is not None
        }
        known_staff_ids = {employee.yclients_staff_id for employee in employees}
        skip_unseen_staff = bool(visible_staff_ids and visible_staff_ids < known_staff_ids)
        remote_stats: list[YClientsDailyStatistic] = []
        day = date_from
        while day <= date_to:
            day_records = records_by_day.get(day, [])
            for employee in employees:
                if skip_unseen_staff and employee.yclients_staff_id not in visible_staff_ids:
                    continue
                remote_stat = _calculate_daily_statistic(
                    employee.yclients_staff_id,
                    day,
                    day_records,
                    include_records_without_staff=False,
                )
                await self._upsert_daily_stat(employee, remote_stat)
                remote_stats.append(remote_stat)
            day += timedelta(days=1)
        return remote_stats

    async def sync_employee_period(
        self,
        employee: Employee,
        date_from: date,
        date_to: date,
    ) -> list[YClientsDailyStatistic]:
        company = await self._companies.get_default()
        if company is None or employee.branch is None:
            return []
        client = await self._client_for_branch(company, employee.branch)
        records = await client.list_records(
            company_id=employee.branch.yclients_branch_id,
            date_from=date_from,
            date_to=date_to,
            employee_staff_id=employee.yclients_staff_id,
        )
        visible_staff_ids = _visible_staff_ids(records)
        if visible_staff_ids and employee.yclients_staff_id not in visible_staff_ids:
            returned_ids = ", ".join(str(staff_id) for staff_id in sorted(visible_staff_ids))
            raise YClientsApiError(
                "YCLIENTS вернул записи другого staff_id вместо выбранного сотрудника. "
                f"Запрошен {employee.yclients_staff_id}, в ответе {returned_ids}. "
                "Текущий User token не видит журнал этого сотрудника или API игнорирует фильтр staff_id."
            )
        records_by_day = _records_by_day(records, date_from=date_from, date_to=date_to)
        remote_stats: list[YClientsDailyStatistic] = []
        day = date_from
        while day <= date_to:
            remote_stat = _calculate_daily_statistic(
                employee.yclients_staff_id,
                day,
                records_by_day.get(day, []),
                include_records_without_staff=True,
            )
            await self._upsert_daily_stat(employee, remote_stat)
            remote_stats.append(remote_stat)
            day += timedelta(days=1)
        return remote_stats

    async def get_period_stats(self, employee: Employee, period: str) -> list:
        start, today = _period_bounds(period)
        return await self._daily_stats.list_period(employee.id, start, today)

    async def refresh_employees_period(
        self,
        employees: list[Employee],
        period: str,
    ) -> list[YClientsDailyStatistic]:
        remote_stats: list[YClientsDailyStatistic] = []
        for employee in employees:
            remote_stats.extend(await self.refresh_period(employee, period))
        return remote_stats

    async def refresh_period(self, employee: Employee, period: str) -> list[YClientsDailyStatistic]:
        start, end = _period_bounds(period)
        cache_key = ("employee", str(employee.id), period, start, end)
        if _is_refresh_cached(cache_key, ttl_seconds=self._settings.yclients_statistics_cache_ttl_seconds):
            return []
        if employee.branch is not None:
            remote_stats = await self.sync_employee_period(employee, start, end)
            _mark_refresh_cached(cache_key)
            return remote_stats
        day = start
        remote_stats: list[YClientsDailyStatistic] = []
        while day <= end:
            remote_stat = await self.sync_employee_day(employee, day)
            if remote_stat is not None:
                remote_stats.append(remote_stat)
            day += timedelta(days=1)
        _mark_refresh_cached(cache_key)
        return remote_stats

    async def refresh_team_period(self, employees: list[Employee], period: str) -> list[YClientsDailyStatistic]:
        start, end = _period_bounds(period)
        remote_stats: list[YClientsDailyStatistic] = []
        grouped = _employees_by_branch(employees)
        for branch, branch_employees in grouped:
            cache_key = ("branch", str(branch.id), period, start, end)
            if _is_refresh_cached(cache_key, ttl_seconds=self._settings.yclients_statistics_cache_ttl_seconds):
                continue
            remote_stats.extend(await self.sync_branch_period(branch, branch_employees, start, end))
            _mark_refresh_cached(cache_key)
        return remote_stats

    async def employee_stats_text(self, employee: Employee, period: str = "month", *, refresh: bool = True) -> str:
        remote_stats: list[YClientsDailyStatistic] = []
        if refresh:
            try:
                remote_stats = await self.refresh_period(employee, period)
            except AppError as exc:
                logger.warning(
                    "employee_stats_refresh_app_error",
                    employee_id=str(employee.id),
                    period=period,
                    error=exc.public_message[:200],
                )
            except Exception as exc:
                logger.exception("employee_stats_refresh_failed", employee_id=str(employee.id), period=period)
        parts = await self.employee_scope_stats_text([employee], period, refresh=False)
        record_lines = _records_summary_lines(remote_stats)
        if record_lines:
            parts.append(pre(["Записи по API", *record_lines]))
        return "\n\n".join(parts)

    async def employee_stats_rich_message(self, employee: Employee, period: str = "month") -> object:
        return await self.employee_scope_stats_rich_message([employee], period)

    async def employee_scope_stats_text(
        self,
        employees: list[Employee],
        period: str = "month",
        *,
        refresh: bool = True,
    ) -> list[str]:
        if refresh:
            await self.refresh_employees_period(employees, period)
        summary = await self._employee_scope_summary(employees, period)
        goal_amount = await self._next_kpi_goal(summary["kpi_base"])
        goal_progress = (
            min(Decimal("100"), summary["kpi_base"] / goal_amount * Decimal("100"))
            if goal_amount and goal_amount > 0
            else Decimal("0")
        )

        sidebar = [
            f"Сотрудник : {summary['employee_name']}",
            f"Филиал   : {summary['scope_label']}",
            f"Грейд    : {summary['grade_label']}",
            f"KPI база : {money(summary['kpi_base'])}",
            f"Цель     : {money(goal_amount) if goal_amount else 'не задана'}",
            f"Прогресс : {progress_bar(goal_progress)} {goal_progress:.0f}%",
        ]
        metrics = [
            f"Стрижек        {summary['haircuts_count']}",
            f"Доп. услуги    {money(summary['additional_services_revenue'])}",
            f"Продажи        {summary['products_sold']} / {money(summary['products_revenue'])}",
            f"ЗП             {money(summary['salary_amount'])}",
            f"Средний чек    {money(summary['average_check'])}",
            f"Посещаемость   {summary['attendance_percent'].quantize(Decimal('0.1'))}%",
        ]
        parts = [
            bold(f"СТАТИСТИКА {_period_title(period)}"),
            pre(_period_lines(period)),
            pre(sidebar),
            pre(metrics),
        ]
        branch_lines = _branch_scope_lines(summary["branch_rows"])
        if branch_lines:
            parts.append(pre(["Филиалы", *branch_lines]))
        return parts

    async def employee_scope_stats_rich_message(self, employees: list[Employee], period: str = "month") -> object:
        summary = await self._employee_scope_summary(employees, period)
        goal_amount = await self._next_kpi_goal(summary["kpi_base"])
        goal_progress = (
            min(Decimal("100"), summary["kpi_base"] / goal_amount * Decimal("100"))
            if goal_amount and goal_amount > 0
            else Decimal("0")
        )
        period_values = _period_values(period)
        blocks = [
            table(
                key_value_rows(
                    [
                        ("Период", period_values["period"]),
                        ("Даты", period_values["dates"]),
                        ("Сотрудник", summary["employee_name"]),
                        ("Филиал", summary["scope_label"]),
                        ("Грейд", summary["grade_label"]),
                    ]
                )
            ),
            table(
                key_value_rows(
                    [
                        ("KPI база", money(summary["kpi_base"])),
                        ("Цель", money(goal_amount) if goal_amount else "не задана"),
                        ("Прогресс", f"{progress_bar(goal_progress)} {goal_progress:.0f}%"),
                    ]
                )
            ),
            table(
                key_value_rows(
                    [
                        ("Стрижек", summary["haircuts_count"]),
                        ("Доп. услуги", money(summary["additional_services_revenue"])),
                        ("Продажи", f"{summary['products_sold']} / {money(summary['products_revenue'])}"),
                        ("ЗП", money(summary["salary_amount"])),
                        ("Средний чек", money(summary["average_check"])),
                        ("Посещаемость", f"{summary['attendance_percent'].quantize(Decimal('0.1'))}%"),
                    ]
                )
            ),
        ]
        if len(summary["branch_rows"]) > 1:
            blocks.append(
                table(
                    table_rows(
                        ["Филиал", "Стр", "Доп.", "Продажи", "ЗП", "Ср. чек"],
                        [
                            [
                                row["branch_name"],
                                row["haircuts_count"],
                                money(row["additional_services_revenue"]),
                                money(row["products_revenue"]),
                                money(row["salary_amount"]),
                                money(row["average_check"]),
                            ]
                            for row in summary["branch_rows"]
                        ],
                        numeric_columns={1, 2, 3, 4, 5},
                    )
                )
            )
        return rich_message(
            f"СТАТИСТИКА {_period_title(period)}",
            *blocks,
        )

    async def team_stats_text(
        self,
        employees: list[Employee],
        period: str,
        *,
        title: str,
        refresh: bool = True,
    ) -> str:
        if not employees:
            return "\n\n".join(
                [
                    bold(f"СТАТИСТИКА {_period_title(period)}"),
                    blockquote("Сотрудники пока не синхронизированы."),
                ]
            )

        limited_staff_by_branch: dict[str, set[int]] = {}
        if refresh:
            for branch, branch_employees in _employees_by_branch(employees):
                try:
                    branch_stats = await self.sync_branch_period(branch, branch_employees, *_period_bounds(period))
                    synced_staff_ids = {stat.employee_staff_id for stat in branch_stats}
                    branch_staff_ids = {employee.yclients_staff_id for employee in branch_employees}
                    if synced_staff_ids and synced_staff_ids < branch_staff_ids:
                        limited_staff_by_branch[str(branch.id)] = synced_staff_ids
                except AppError as exc:
                    logger.warning(
                        "team_stats_refresh_app_error",
                        branch_id=str(branch.id),
                        period=period,
                        employees=len(branch_employees),
                        error=exc.public_message[:200],
                    )
                except Exception as exc:
                    logger.exception("team_stats_refresh_failed", branch_id=str(branch.id), period=period)

        rows = []
        for employee in employees:
            branch_key = str(employee.branch_id) if employee.branch_id else None
            limited_staff_ids = limited_staff_by_branch.get(branch_key or "")
            data_unavailable = limited_staff_ids is not None and employee.yclients_staff_id not in limited_staff_ids
            if data_unavailable:
                stats = []
                haircuts_count = 0
                service_revenue = Decimal("0")
                additional_services_revenue = Decimal("0")
                products_sold = 0
                products_revenue = Decimal("0")
                total_revenue = Decimal("0")
            else:
                stats = await self.get_period_stats(employee, period)
                haircuts_count = sum(item.haircuts_count for item in stats)
                service_revenue = sum((item.service_revenue for item in stats), Decimal("0"))
                additional_services_revenue = sum(
                    (item.additional_services_revenue for item in stats), Decimal("0")
                )
            products_sold = sum(item.products_sold for item in stats)
            products_revenue = sum((item.products_revenue for item in stats), Decimal("0"))
            total_revenue = sum((item.total_revenue for item in stats), Decimal("0"))
            average_check = total_revenue / haircuts_count if haircuts_count else Decimal("0")
            rows.append(
                {
                    "employee": employee,
                    "data_unavailable": data_unavailable,
                    "haircuts_count": haircuts_count,
                    "service_revenue": service_revenue,
                    "additional_services_revenue": additional_services_revenue,
                    "products_sold": products_sold,
                    "products_revenue": products_revenue,
                    "total_revenue": total_revenue,
                    "average_check": average_check,
                    "kpi_base": additional_services_revenue + products_revenue,
                    "stats_count": len(stats),
                }
            )

        total_haircuts = sum(row["haircuts_count"] for row in rows)
        service_revenue = sum((row["service_revenue"] for row in rows), Decimal("0"))
        additional_services_revenue = sum((row["additional_services_revenue"] for row in rows), Decimal("0"))
        products_sold = sum(row["products_sold"] for row in rows)
        products_revenue = sum((row["products_revenue"] for row in rows), Decimal("0"))
        total_revenue = sum((row["total_revenue"] for row in rows), Decimal("0"))
        average_check = total_revenue / total_haircuts if total_haircuts else Decimal("0")
        service_income = service_revenue + additional_services_revenue
        kpi_base = additional_services_revenue + products_revenue
        unavailable_rows = [row for row in rows if row["data_unavailable"]]
        available_rows_count = len(rows) - len(unavailable_rows)

        summary = [
            f"Группа       {title}",
            *_period_lines(period),
            f"Сотрудников {len(employees)}",
            *([f"Данные API  {available_rows_count} из {len(employees)}"] if unavailable_rows else []),
            f"Стрижек     {total_haircuts}",
            f"Доход услуг {money(service_income)}",
            f"Основные    {money(service_revenue)}",
            f"Доп. услуги {money(additional_services_revenue)}",
            f"KPI база    {money(kpi_base)}",
            f"Товары      {products_sold} / {money(products_revenue)}",
            f"Выручка     {money(total_revenue)}",
            f"Средний чек {money(average_check)}",
        ]
        table = [f"{'Филиал':11} {'Сотрудник':16} {'Стр':>3} {'Ср.чек':>8} {'Выручка':>11} {'KPI база':>11}"]
        for row in sorted(rows, key=lambda item: item["total_revenue"], reverse=True):
            employee = row["employee"]
            branch_name = _branch_table_label(employee)
            if row["data_unavailable"]:
                table.append(
                    f"{branch_name:11} {shorten(employee.full_name, 16):16} "
                    f"{'-':>3} {'-':>8} {'нет данных':>11} {'-':>11}"
                )
            else:
                table.append(
                    f"{branch_name:11} "
                    f"{shorten(employee.full_name, 16):16} "
                    f"{row['haircuts_count']:>3} "
                    f"{money(row['average_check']):>8} "
                    f"{money(row['total_revenue']):>11} "
                    f"{money(row['kpi_base']):>11}"
                )

        parts = [
            bold(f"СТАТИСТИКА {_period_title(period)}"),
            pre(summary),
            pre(table),
        ]
        return "\n\n".join(parts)

    async def team_stats_rich_message(
        self,
        employees: list[Employee],
        period: str,
        *,
        title: str,
    ) -> object:
        if not employees:
            return rich_message(
                f"СТАТИСТИКА {_period_title(period)}",
                paragraph("Сотрудники пока не синхронизированы."),
            )

        rows = []
        for employee in employees:
            stats = await self.get_period_stats(employee, period)
            haircuts_count = sum(item.haircuts_count for item in stats)
            service_revenue = sum((item.service_revenue for item in stats), Decimal("0"))
            additional_services_revenue = sum((item.additional_services_revenue for item in stats), Decimal("0"))
            products_revenue = sum((item.products_revenue for item in stats), Decimal("0"))
            total_revenue = sum((item.total_revenue for item in stats), Decimal("0"))
            average_check = total_revenue / haircuts_count if haircuts_count else Decimal("0")
            rows.append(
                {
                    "employee": employee,
                    "haircuts_count": haircuts_count,
                    "service_revenue": service_revenue,
                    "additional_services_revenue": additional_services_revenue,
                    "products_revenue": products_revenue,
                    "total_revenue": total_revenue,
                    "average_check": average_check,
                    "kpi_base": additional_services_revenue + products_revenue,
                }
            )

        total_haircuts = sum(row["haircuts_count"] for row in rows)
        service_revenue = sum((row["service_revenue"] for row in rows), Decimal("0"))
        additional_services_revenue = sum((row["additional_services_revenue"] for row in rows), Decimal("0"))
        products_revenue = sum((row["products_revenue"] for row in rows), Decimal("0"))
        total_revenue = sum((row["total_revenue"] for row in rows), Decimal("0"))
        average_check = total_revenue / total_haircuts if total_haircuts else Decimal("0")
        kpi_base = additional_services_revenue + products_revenue
        period_values = _period_values(period)
        employee_rows = [
            [
                _branch_table_label(row["employee"]),
                row["employee"].full_name,
                row["haircuts_count"],
                money(row["average_check"]),
                money(row["total_revenue"]),
                money(row["kpi_base"]),
            ]
            for row in sorted(rows, key=lambda item: item["total_revenue"], reverse=True)
        ]
        return rich_message(
            f"СТАТИСТИКА {_period_title(period)}",
            table(
                key_value_rows(
                    [
                        ("Группа", title),
                        ("Период", period_values["period"]),
                        ("Даты", period_values["dates"]),
                        ("Сотрудников", len(employees)),
                        ("Стрижек", total_haircuts),
                        ("Доход услуг", money(service_revenue + additional_services_revenue)),
                        ("KPI база", money(kpi_base)),
                        ("Выручка", money(total_revenue)),
                        ("Средний чек", money(average_check)),
                    ]
                )
            ),
            table(
                table_rows(
                    ["Филиал", "Сотрудник", "Стр", "Ср. чек", "Выручка", "KPI"],
                    employee_rows,
                    numeric_columns={2, 3, 4, 5},
                )
            ),
        )

    def _client_for_company(self, company: Company) -> YClientsClient:
        return self._client(
            company,
            user_token=self._company_user_token(company),
            partner_token=self._encryption.decrypt(company.encrypted_yclients_api_key),
        )

    async def _client_for_branch(self, company: Company, branch: Branch) -> YClientsClient:
        user_token = self._company_user_token(company)
        if branch.owner_telegram_user_id is not None:
            franchisee = await self._franchisees.get_by_telegram_user_id(branch.owner_telegram_user_id)
            if franchisee and not franchisee.is_blocked:
                owner_token = self._encryption.decrypt(franchisee.encrypted_yclients_user_token)
                if owner_token:
                    user_token = owner_token
        return self._client(
            company,
            user_token=user_token,
            partner_token=self._encryption.decrypt(company.encrypted_yclients_api_key),
        )

    def _client(self, company: Company, *, user_token: str | None, partner_token: str | None) -> YClientsClient:
        return YClientsClient(
            base_url=self._settings.yclients_base_url_str,
            partner_token=partner_token or self._settings.yclients_partner_token,
            user_token=user_token,
            timeout_seconds=self._settings.yclients_timeout_seconds,
            product_max_pages=self._settings.yclients_product_max_pages,
        )

    def _company_user_token(self, company: Company) -> str | None:
        return self._encryption.decrypt(company.encrypted_yclients_user_token) or self._settings.yclients_user_token

    async def _upsert_daily_stat(self, employee: Employee, remote_stat: YClientsDailyStatistic) -> None:
        await self._daily_stats.upsert(
            employee_id=employee.id,
            statistic_date=remote_stat.statistic_date,
            haircuts_count=remote_stat.haircuts_count,
            service_revenue=remote_stat.service_revenue,
            additional_services_revenue=remote_stat.additional_services_revenue,
            total_revenue=remote_stat.total_revenue,
            average_check=remote_stat.average_check,
            attendance_percent=remote_stat.attendance_percent,
            products_sold=remote_stat.products_sold,
            products_revenue=remote_stat.products_revenue,
        )

    async def _employee_scope_summary(self, employees: list[Employee], period: str) -> dict:
        branch_rows = []
        all_stats = []
        employee_names = []
        grade_titles = []
        for employee in employees:
            stats = await self.get_period_stats(employee, period)
            all_stats.extend(stats)
            employee_names.append(employee.full_name)
            if employee.category_title:
                grade_titles.append(employee.category_title)
            haircuts_count = sum(item.haircuts_count for item in stats)
            total_revenue = sum((item.total_revenue for item in stats), Decimal("0"))
            additional_services_revenue = sum((item.additional_services_revenue for item in stats), Decimal("0"))
            products_sold = sum(item.products_sold for item in stats)
            products_revenue = sum((item.products_revenue for item in stats), Decimal("0"))
            salary_amount = additional_services_revenue + products_revenue
            attendance_percent = _average_attendance(stats)
            branch_rows.append(
                {
                    "employee": employee,
                    "branch_name": employee.branch.name if employee.branch else "не указан",
                    "haircuts_count": haircuts_count,
                    "additional_services_revenue": additional_services_revenue,
                    "products_sold": products_sold,
                    "products_revenue": products_revenue,
                    "salary_amount": salary_amount,
                    "total_revenue": total_revenue,
                    "average_check": total_revenue / haircuts_count if haircuts_count else Decimal("0"),
                    "attendance_percent": attendance_percent,
                }
            )
        haircuts_count = sum(item.haircuts_count for item in all_stats)
        total_revenue = sum((item.total_revenue for item in all_stats), Decimal("0"))
        additional_services_revenue = sum((item.additional_services_revenue for item in all_stats), Decimal("0"))
        products_sold = sum(item.products_sold for item in all_stats)
        products_revenue = sum((item.products_revenue for item in all_stats), Decimal("0"))
        salary_amount = additional_services_revenue + products_revenue
        branch_rows = sorted(branch_rows, key=lambda row: row["salary_amount"], reverse=True)
        unique_branches = [row["branch_name"] for row in branch_rows]
        return {
            "employee_name": _same_or_join(employee_names, fallback="сотрудник"),
            "scope_label": unique_branches[0] if len(unique_branches) == 1 else f"все филиалы ({len(unique_branches)})",
            "grade_label": _same_or_join(grade_titles, fallback="не указан"),
            "haircuts_count": haircuts_count,
            "additional_services_revenue": additional_services_revenue,
            "products_sold": products_sold,
            "products_revenue": products_revenue,
            "salary_amount": salary_amount,
            "kpi_base": salary_amount,
            "total_revenue": total_revenue,
            "average_check": total_revenue / haircuts_count if haircuts_count else Decimal("0"),
            "attendance_percent": _average_attendance(all_stats),
            "branch_rows": branch_rows,
        }

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


def money(value: Decimal) -> str:
    return format_money(value)


def yclients_data_error_hint(message: str) -> str:
    lowered = message.casefold()
    if "недостаточно прав" in lowered or "403" in lowered:
        return (
            "YCLIENTS принял User token, но у пользователя нет прав на записи/финансы выбранного филиала. "
            "Нужно выдать этому пользователю доступ к филиалу и права на журнал записей, финансы и просмотр оплат."
        )
    if "401" in lowered or "идентификатор пользователя" in lowered or "user token" in lowered:
        return (
            "YCLIENTS не увидел User token для записей, статистики и финансов. "
            "Проверьте, что в настройках сохранён именно полный User token, а не Partner ID или API key."
        )
    return message


def _period_bounds(period: str) -> tuple[date, date]:
    today = date.today()
    kind, start = _period_kind_and_start(period, today=today)
    if kind == "day":
        end = start
    elif kind == "week":
        end = start + timedelta(days=6)
    else:
        end = _add_months(start, 1) - timedelta(days=1)
    if end > today:
        end = today
    if start > today:
        start = today
        end = today
    return start, end


def _period_title(period: str) -> str:
    kind, _ = _period_kind_and_start(period)
    return {
        "day": "ЗА ДЕНЬ",
        "week": "ЗА НЕДЕЛЮ",
        "month": "ЗА МЕСЯЦ",
    }.get(kind, "ЗА ПЕРИОД")


def canonical_period(period: str) -> str:
    kind, start = _period_kind_and_start(period)
    return _period_code(kind, start)


def shifted_period(period: str, step: int) -> str:
    today = date.today()
    kind, start = _period_kind_and_start(period, today=today)
    if kind == "day":
        shifted = start + timedelta(days=step)
    elif kind == "week":
        shifted = start + timedelta(days=step * 7)
    else:
        shifted = _add_months(start, step)
    current_kind_start = _period_kind_start(kind, today)
    if shifted > current_kind_start:
        shifted = current_kind_start
    return _period_code(kind, shifted)


def period_kind(period: str) -> str:
    kind, _ = _period_kind_and_start(period)
    return kind


def _period_lines(period: str) -> list[str]:
    values = _period_values(period)
    return [
        f"Период      {values['period']}",
        f"Даты        {values['dates']}",
    ]


def _period_values(period: str) -> dict[str, str]:
    start, end = _period_bounds(period)
    kind = period_kind(period)
    if kind == "day":
        period_label = f"{start.day} {_month_genitive(start)} {start.year}"
    elif kind == "week":
        period_label = f"неделя {_date_range_label(start, end)}"
    elif start.month == end.month and start.year == end.year:
        period_label = _month_label(start)
    else:
        period_label = f"{_month_label(start)} - {_month_label(end)}"
    return {"month": period_label, "period": period_label, "dates": _date_range_label(start, end)}


def _period_kind_and_start(period: str, *, today: date | None = None) -> tuple[str, date]:
    today = today or date.today()
    value = (period or "").strip().casefold()
    if value == "today":
        return "day", today
    if value == "week":
        return "week", _period_kind_start("week", today)
    if value == "month":
        return "month", _period_kind_start("month", today)
    if value == "previous_month":
        return "month", _add_months(_period_kind_start("month", today), -1)
    if len(value) == 9 and value[0] in {"d", "w", "m"}:
        try:
            anchor = date(int(value[1:5]), int(value[5:7]), int(value[7:9]))
        except ValueError:
            return "day", today
        kind = {"d": "day", "w": "week", "m": "month"}[value[0]]
        return kind, _period_kind_start(kind, anchor)
    return "day", today


def _period_kind_start(kind: str, anchor: date) -> date:
    if kind == "week":
        return anchor - timedelta(days=anchor.weekday())
    if kind == "month":
        return anchor.replace(day=1)
    return anchor


def _period_code(kind: str, start: date) -> str:
    prefix = {"day": "d", "week": "w", "month": "m"}[kind]
    return f"{prefix}{start:%Y%m%d}"


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year = month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month, day=1)


def _month_label(value: date) -> str:
    return f"{_MONTH_NAMES[value.month - 1]} {value.year}"


def _month_genitive(value: date) -> str:
    names = (
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    )
    return names[value.month - 1]


def _date_range_label(start: date, end: date) -> str:
    if start == end:
        return f"{start:%d.%m.%Y}"
    if start.year == end.year:
        return f"{start:%d.%m}-{end:%d.%m.%Y}"
    return f"{start:%d.%m.%Y}-{end:%d.%m.%Y}"


def _records_by_day(
    records: list[dict],
    *,
    date_from: date,
    date_to: date,
) -> dict[date, list[dict]]:
    grouped: dict[date, list[dict]] = defaultdict(list)
    single_day = date_from == date_to
    for record in records:
        record_day = _record_statistic_date(record)
        if record_day is None:
            if single_day:
                grouped[date_from].append(record)
            continue
        if date_from <= record_day <= date_to:
            grouped[record_day].append(record)
    return grouped


def _visible_staff_ids(records: list[dict]) -> set[int]:
    return {
        staff_id
        for staff_id in (_record_staff_id(record) for record in records)
        if staff_id is not None
    }


def _employees_by_branch(employees: list[Employee]) -> list[tuple[Branch, list[Employee]]]:
    by_branch: dict[str, tuple[Branch, list[Employee]]] = {}
    for employee in employees:
        if employee.branch is None:
            continue
        branch_key = str(employee.branch.id)
        if branch_key not in by_branch:
            by_branch[branch_key] = (employee.branch, [])
        by_branch[branch_key][1].append(employee)
    return list(by_branch.values())


def _branch_table_label(employee: Employee) -> str:
    if employee.branch is None:
        return "-"
    name = employee.branch.name.replace("KREMEN", "").strip(" ·-")
    return shorten(name or employee.branch.name, 11)


def _branch_scope_lines(branch_rows: list[dict]) -> list[str]:
    if len(branch_rows) <= 1:
        return []
    lines = [f"{'Филиал':16} {'Стр':>4} {'Доп.':>10} {'Продажи':>10} {'ЗП':>10}"]
    for row in branch_rows:
        lines.append(
            f"{shorten(row['branch_name'], 16):16} "
            f"{row['haircuts_count']:>4} "
            f"{money(row['additional_services_revenue']):>10} "
            f"{money(row['products_revenue']):>10} "
            f"{money(row['salary_amount']):>10}"
        )
    return lines


def _average_attendance(stats: list) -> Decimal:
    if not stats:
        return Decimal("0")
    return sum((item.attendance_percent for item in stats), Decimal("0")) / len(stats)


def _same_or_join(values: list[str], *, fallback: str) -> str:
    cleaned = []
    for value in values:
        value = value.strip()
        if value and value not in cleaned:
            cleaned.append(value)
    if not cleaned:
        return fallback
    if len(cleaned) == 1:
        return cleaned[0]
    return " / ".join(cleaned[:3])


def _records_summary_lines(remote_stats: list[YClientsDailyStatistic]) -> list[str]:
    records = [
        record
        for day_stat in remote_stats
        for record in day_stat.raw_payload.get("records", [])
        if isinstance(record, dict)
    ]
    if not records:
        return []
    attended_records = [record for record in records if _is_attended_record(record)]
    completed = len(attended_records)
    cancelled = sum(1 for record in records if _is_cancelled_record(record))
    unfinished = max(0, len(records) - completed - cancelled)
    client_records = [record for record in attended_records if isinstance(record.get("client"), dict)]
    new_clients = sum(1 for record in client_records if _boolish_client_value(record["client"].get("is_new")))
    repeat_clients = len(client_records) - new_clients
    return [
        f"Всего       {len(records)}",
        f"Завершено   {completed} / {_percent_text(completed, len(records))}",
        f"Отменено    {cancelled} / {_percent_text(cancelled, len(records))}",
        f"Не заверш.  {unfinished} / {_percent_text(unfinished, len(records))}",
        f"Новые       {new_clients} / {_percent_text(new_clients, len(client_records))}",
        f"Повторные   {repeat_clients} / {_percent_text(repeat_clients, len(client_records))}",
    ]


def _service_lines_by_day(remote_stats: list[YClientsDailyStatistic], *, limit: int = 18) -> list[str]:
    lines: list[str] = []
    hidden = 0
    for day_stat in remote_stats:
        records = day_stat.raw_payload.get("records", [])
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict) or not _is_attended_record(record):
                continue
            services = _record_services(record)
            for service in services:
                if len(lines) >= limit:
                    hidden += 1
                    continue
                title = str(service.get("title") or service.get("name") or service.get("booking_title") or "Услуга")
                amount = _decimal(service.get("cost") or service.get("price") or service.get("sum") or 0)
                lines.append(f"{day_stat.statistic_date:%d.%m}  {title[:24]:24} {money(amount)}")
    if hidden:
        lines.append(f"... ещё услуг: {hidden}")
    return lines


def _record_services(record: dict) -> list[dict]:
    services = record.get("services") or record.get("visit_services") or []
    return [item for item in services if isinstance(item, dict)] if isinstance(services, list) else []


def _is_attended_record(record: dict) -> bool:
    attendance = record.get("attendance")
    if attendance is None:
        return True
    return str(attendance) not in {"-1", "0", "not_come", "no_show", "cancelled"}


def _is_cancelled_record(record: dict) -> bool:
    attendance = str(record.get("attendance") or "").casefold()
    return attendance in {"-1", "not_come", "no_show", "cancelled"}


def _boolish_client_value(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "да"}


def _percent_text(part: int, total: int) -> str:
    if total <= 0:
        return "0%"
    value = Decimal(part) / Decimal(total) * Decimal("100")
    return f"{value.quantize(Decimal('0.1'))}%"


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _is_refresh_cached(
    cache_key: tuple[str, str, str, date, date],
    *,
    ttl_seconds: int,
) -> bool:
    if ttl_seconds <= 0:
        return False
    cached_at = _REFRESH_CACHE.get(cache_key)
    if cached_at is None:
        return False
    if monotonic() - cached_at > ttl_seconds:
        _REFRESH_CACHE.pop(cache_key, None)
        return False
    return True


def _mark_refresh_cached(cache_key: tuple[str, str, str, date, date]) -> None:
    _REFRESH_CACHE[cache_key] = monotonic()
