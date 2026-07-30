from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.config.settings import Settings
from app.models import Branch, Employee
from app.repositories import CompanyRepository, DailyStatisticRepository, KpiRuleRepository
from app.services.security import EncryptionService
from app.utils.exceptions import AppError
from app.utils.telegram_formatting import blockquote, bold, money as format_money, pre, progress_bar
from app.yclients.client import YClientsClient, _calculate_daily_statistic, _record_statistic_date
from app.yclients.types import YClientsDailyStatistic

logger = get_logger(__name__)


class StatisticsService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._companies = CompanyRepository(session)
        self._daily_stats = DailyStatisticRepository(session)
        self._kpi_rules = KpiRuleRepository(session)
        self._encryption = EncryptionService(settings)

    async def sync_employee_day(self, employee: Employee, statistic_date: date) -> YClientsDailyStatistic | None:
        company = await self._companies.get_default()
        if company is None:
            return None
        client = self._client_for_company(company)
        branch = employee.branch
        if branch is None:
            return None
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
        client = self._client_for_company(company)
        records = await client.list_records(
            company_id=branch.yclients_branch_id,
            date_from=date_from,
            date_to=date_to,
        )
        records_by_day = _records_by_day(records, date_from=date_from, date_to=date_to)
        remote_stats: list[YClientsDailyStatistic] = []
        day = date_from
        while day <= date_to:
            day_records = records_by_day.get(day, [])
            for employee in employees:
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
        client = self._client_for_company(company)
        records = await client.list_records(
            company_id=employee.branch.yclients_branch_id,
            date_from=date_from,
            date_to=date_to,
            employee_staff_id=employee.yclients_staff_id,
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

    async def refresh_period(self, employee: Employee, period: str) -> list[YClientsDailyStatistic]:
        start, end = _period_bounds(period)
        if employee.branch is not None:
            return await self.sync_employee_period(employee, start, end)
        day = start
        remote_stats: list[YClientsDailyStatistic] = []
        while day <= end:
            remote_stat = await self.sync_employee_day(employee, day)
            if remote_stat is not None:
                remote_stats.append(remote_stat)
            day += timedelta(days=1)
        return remote_stats

    async def refresh_team_period(self, employees: list[Employee], period: str) -> list[YClientsDailyStatistic]:
        start, end = _period_bounds(period)
        remote_stats: list[YClientsDailyStatistic] = []
        grouped = _employees_by_branch(employees)
        for branch, branch_employees in grouped:
            remote_stats.extend(await self.sync_branch_period(branch, branch_employees, start, end))
        return remote_stats

    async def employee_stats_text(self, employee: Employee, period: str = "month", *, refresh: bool = True) -> str:
        refresh_warning: str | None = None
        remote_stats: list[YClientsDailyStatistic] = []
        if refresh:
            try:
                remote_stats = await self.refresh_period(employee, period)
            except AppError as exc:
                refresh_warning = yclients_data_error_hint(exc.public_message)
            except Exception as exc:
                logger.exception("employee_stats_refresh_failed", employee_id=str(employee.id), period=period)
                refresh_warning = yclients_data_error_hint(f"Не удалось обновить данные из YCLIENTS: {str(exc)[:200]}")
        stats = await self.get_period_stats(employee, period)
        title = {
            "today": "СЕГОДНЯ",
            "week": "ЗА НЕДЕЛЮ",
            "month": "ЗА МЕСЯЦ",
            "previous_month": "ЗА ПРОШЛЫЙ МЕСЯЦ",
        }.get(period, "ЗА ПЕРИОД")
        haircuts_count = sum(item.haircuts_count for item in stats)
        service_revenue = sum((item.service_revenue for item in stats), Decimal("0"))
        additional_services_revenue = sum(
            (item.additional_services_revenue for item in stats), Decimal("0")
        )
        products_sold = sum(item.products_sold for item in stats)
        products_revenue = sum((item.products_revenue for item in stats), Decimal("0"))
        total_revenue = sum((item.total_revenue for item in stats), Decimal("0"))
        average_check = total_revenue / haircuts_count if haircuts_count else Decimal("0")
        attendance_percent = (
            sum((item.attendance_percent for item in stats), Decimal("0")) / len(stats)
            if stats
            else Decimal("0")
        )
        kpi_base = service_revenue + additional_services_revenue
        goal_amount = await self._next_kpi_goal(kpi_base)
        goal_progress = (
            min(Decimal("100"), kpi_base / goal_amount * Decimal("100"))
            if goal_amount and goal_amount > 0
            else Decimal("0")
        )

        sidebar = [
            f"Сотрудник : {employee.full_name}",
            f"Грейд    : {employee.category_title or 'не указан'}",
            f"KPI база : {money(kpi_base)}",
            f"Цель     : {money(goal_amount) if goal_amount else 'не задана'}",
            f"Прогресс : {progress_bar(goal_progress)} {goal_progress:.0f}%",
        ]
        metrics = [
            f"Стрижек             {haircuts_count}",
            f"Услуги              {money(service_revenue)}",
            f"Доп. услуги         {money(additional_services_revenue)}",
            f"Общая выручка       {money(total_revenue)}",
            f"Средний чек         {money(average_check)}",
            f"Посещаемость        {attendance_percent:.1f}%",
            f"Товаров продано     {products_sold}",
            f"Выручка по товарам  {money(products_revenue)}",
        ]
        parts = [
            bold(f"СТАТИСТИКА {title}"),
            pre(_period_lines(period)),
            pre(sidebar),
            pre(metrics),
        ]
        service_lines = _service_lines_by_day(remote_stats)
        if service_lines:
            parts.append(pre(["Услуги по дням", *service_lines]))
        digest = _stats_digest(
            employee=employee,
            stats_count=len(stats),
            haircuts_count=haircuts_count,
            total_revenue=total_revenue,
            refresh_warning=refresh_warning,
        )
        if digest:
            parts.append(blockquote(digest))
        return "\n\n".join(parts)

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

        refresh_errors = 0
        first_refresh_warning: str | None = None
        if refresh:
            for branch, branch_employees in _employees_by_branch(employees):
                try:
                    await self.sync_branch_period(branch, branch_employees, *_period_bounds(period))
                except AppError as exc:
                    refresh_errors += len(branch_employees)
                    if first_refresh_warning is None:
                        first_refresh_warning = yclients_data_error_hint(exc.public_message)
                except Exception as exc:
                    logger.exception("team_stats_refresh_failed", branch_id=str(branch.id), period=period)
                    refresh_errors += len(branch_employees)
                    if first_refresh_warning is None:
                        first_refresh_warning = yclients_data_error_hint(
                            f"Не удалось обновить данные из YCLIENTS: {str(exc)[:200]}"
                        )

        rows = []
        for employee in employees:
            stats = await self.get_period_stats(employee, period)
            haircuts_count = sum(item.haircuts_count for item in stats)
            service_revenue = sum((item.service_revenue for item in stats), Decimal("0"))
            additional_services_revenue = sum(
                (item.additional_services_revenue for item in stats), Decimal("0")
            )
            products_sold = sum(item.products_sold for item in stats)
            products_revenue = sum((item.products_revenue for item in stats), Decimal("0"))
            total_revenue = sum((item.total_revenue for item in stats), Decimal("0"))
            rows.append(
                {
                    "employee": employee,
                    "haircuts_count": haircuts_count,
                    "service_revenue": service_revenue,
                    "additional_services_revenue": additional_services_revenue,
                    "products_sold": products_sold,
                    "products_revenue": products_revenue,
                    "total_revenue": total_revenue,
                    "kpi_base": service_revenue + additional_services_revenue,
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
        kpi_base = service_revenue + additional_services_revenue

        summary = [
            f"Группа       {title}",
            f"Период      {_period_title(period)}",
            *_period_lines(period),
            f"Сотрудников {len(employees)}",
            f"Стрижек     {total_haircuts}",
            f"Услуги      {money(service_revenue)}",
            f"Доп. услуги {money(additional_services_revenue)}",
            f"KPI база    {money(kpi_base)}",
            f"Товары      {products_sold} / {money(products_revenue)}",
            f"Выручка     {money(total_revenue)}",
            f"Средний чек {money(average_check)}",
        ]
        table = [f"{'Сотрудник':18} {'Стр':>3} {'Выручка':>11} {'KPI':>11}"]
        for row in sorted(rows, key=lambda item: item["total_revenue"], reverse=True):
            employee = row["employee"]
            table.append(
                f"{employee.full_name[:18]:18} "
                f"{row['haircuts_count']:>3} "
                f"{money(row['total_revenue']):>11} "
                f"{money(row['kpi_base']):>11}"
            )

        digest = []
        zero_rows = [row for row in rows if row["stats_count"] == 0]
        if refresh_errors:
            digest.append(f"ДАЙДЖЕСТ: по {refresh_errors} сотрудникам YCLIENTS не обновил данные.")
            if first_refresh_warning:
                digest.append(first_refresh_warning)
        if zero_rows:
            digest.append(f"ДАЙДЖЕСТ: по {len(zero_rows)} сотрудникам нет дневных строк за период.")
        if total_revenue == 0:
            digest.append("ДАЙДЖЕСТ: общая выручка за выбранный период равна 0 ₽.")

        parts = [
            bold(f"СТАТИСТИКА {_period_title(period)}"),
            pre(summary),
            pre(table),
        ]
        if digest:
            parts.append(blockquote(digest))
        return "\n\n".join(parts)

    def _client_for_company(self, company) -> YClientsClient:
        return YClientsClient(
            base_url=self._settings.yclients_base_url_str,
            partner_token=self._encryption.decrypt(company.encrypted_yclients_api_key)
            or self._settings.yclients_partner_token,
            user_token=self._encryption.decrypt(company.encrypted_yclients_user_token)
            or self._settings.yclients_user_token,
            timeout_seconds=self._settings.yclients_timeout_seconds,
        )

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
    if period == "today":
        return today, today
    if period == "week":
        return today - timedelta(days=today.weekday()), today
    if period == "month":
        return today.replace(day=1), today
    if period == "previous_month":
        current_month_start = today.replace(day=1)
        previous_month_end = current_month_start - timedelta(days=1)
        return previous_month_end.replace(day=1), previous_month_end
    return today, today


def _period_title(period: str) -> str:
    return {
        "today": "ЗА ДЕНЬ",
        "week": "ЗА НЕДЕЛЮ",
        "month": "ЗА МЕСЯЦ",
        "previous_month": "ЗА ПРОШЛЫЙ МЕСЯЦ",
    }.get(period, "ЗА ПЕРИОД")


def _period_lines(period: str) -> list[str]:
    start, end = _period_bounds(period)
    month_label = (
        f"{start:%m.%Y}"
        if start.month == end.month and start.year == end.year
        else f"{start:%m.%Y}-{end:%m.%Y}"
    )
    return [
        f"Месяц       {month_label}",
        f"Даты        {_date_range_label(start, end)}",
    ]


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


def _stats_digest(
    *,
    employee: Employee,
    stats_count: int,
    haircuts_count: int,
    total_revenue: Decimal,
    refresh_warning: str | None,
) -> list[str]:
    digest: list[str] = []
    if employee.branch is None:
        digest.append("ДАЙДЖЕСТ: у сотрудника не найден филиал, поэтому YCLIENTS не знает, откуда брать записи.")
    if refresh_warning:
        digest.append(f"ДАЙДЖЕСТ: свежие данные не подтянулись: {refresh_warning}")
    if stats_count == 0:
        digest.append("ДАЙДЖЕСТ: в локальной базе нет дневных строк за период.")
    elif haircuts_count == 0:
        digest.append("ДАЙДЖЕСТ: строки есть, но посещений за период нет.")
    elif total_revenue == 0:
        digest.append("ДАЙДЖЕСТ: посещения есть, но YCLIENTS вернул нулевую выручку.")
    if digest:
        digest.append(
            "Для полной статистики нужны: рабочий API key, права ключа/токена на записи и финансы, "
            "точный ID филиала, staff_id сотрудника и правило, какие статусы записей считать оплаченными."
        )
    return digest


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


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")
