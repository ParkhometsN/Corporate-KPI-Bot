from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.models import Employee, GradeRule
from app.repositories import CompanyRepository, DailyStatisticRepository, GradeRuleRepository
from app.services.statistics import StatisticsService, _date_range_label, money, yclients_data_error_hint
from app.utils.exceptions import AppError
from app.utils.telegram_formatting import blockquote, bold, pre, progress_bar as telegram_progress_bar


class GradeService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._companies = CompanyRepository(session)
        self._daily_stats = DailyStatisticRepository(session)
        self._grade_rules = GradeRuleRepository(session)
        self._statistics = StatisticsService(session, settings)

    async def grade_text(self, employee: Employee) -> str:
        company = await self._companies.get_default()
        if company is None:
            return "\n\n".join(
                [
                    bold("GRADE UP"),
                    blockquote("Компания не настроена, поэтому правила роста недоступны."),
                ]
            )
        rules = await self._grade_rules.ensure_defaults(company.id)
        current_rule, next_rule = _find_current_and_next(rules, employee.category_title)
        current_grade_label = (
            _rule_display_title(current_rule)
            if current_rule is not None
            else employee.category_title or "без грейда"
        )
        if next_rule is None:
            return "\n\n".join(
                [
                    bold("GRADE UP"),
                    pre(
                        [
                            f"Сотрудник  {employee.full_name}",
                            f"Категория  {current_grade_label}",
                        ]
                    ),
                    blockquote(
                        "Вы уже на максимальной категории."
                        if current_rule is not None
                        else "Правила Grade Up пока не настроены."
                    ),
                ]
            )

        grade_period_start, grade_period_end = _grade_period_bounds(next_rule.months_required)
        refresh_warning: str | None = None
        try:
            await self._statistics.sync_employee_period(employee, grade_period_start, grade_period_end)
        except AppError as exc:
            refresh_warning = yclients_data_error_hint(exc.public_message)
        except Exception as exc:
            refresh_warning = yclients_data_error_hint(f"Не удалось обновить данные из YCLIENTS: {str(exc)[:200]}")

        progress = await self._calculate_progress(employee, next_rule, grade_period_start, grade_period_end)
        tenure_scope = _tenure_scope(next_rule)
        progress_lines = [
            f"Период      {_date_range_label(grade_period_start, grade_period_end)}",
            f"Дней выруч. {progress.revenue_days}",
            f"Выручка усл {money(progress.service_revenue)}",
            f"Средн./дн.  {money(progress.average_daily_revenue)}",
            f"Цель/дн.    {money(next_rule.average_daily_revenue_required)}",
            f"До цели/дн. {money(progress.daily_revenue_left)}",
            f"Стаж {tenure_scope:5} {_tenure_line(progress.tenure_months, next_rule.minimum_employment_months)}",
            f"Прогресс    {telegram_progress_bar(progress.overall_percent)} {progress.overall_percent:.0f}%",
        ]
        digest = [
            "Прогресс считается по средней дневной выручке услуг за дни с выручкой в указанном периоде.",
            "Товары в Grade Up не входят.",
        ]
        if progress.tenure_months is None:
            digest.append("Дата начала работы/категории не заполнена, поэтому стаж сейчас не ограничивает прогресс.")
        if refresh_warning:
            digest.insert(0, f"ДАЙДЖЕСТ: свежие данные не подтянулись: {refresh_warning}")
        return "\n\n".join(
            [
                bold("GRADE UP"),
                pre(
                    [
                        f"Сотрудник   {employee.full_name}",
                        f"Филиал      {employee.branch.name if employee.branch else 'не указан'}",
                        f"Грейд       {employee.category_title or 'не указан'}",
                        f"Сейчас      {current_grade_label}",
                        f"Следующий   {_rule_display_title(next_rule)}",
                        f"Условие     {next_rule.months_required} мес. / {money(next_rule.average_daily_revenue_required)} в день",
                    ]
                ),
                pre(progress_lines),
                blockquote(digest),
            ]
        )

    async def _calculate_progress(
        self,
        employee: Employee,
        rule: GradeRule,
        date_from: date,
        date_to: date,
    ) -> "GradeProgress":
        stats = await self._daily_stats.list_period(employee.id, date_from, date_to)
        total_revenue = sum(
            (item.service_revenue + item.additional_services_revenue for item in stats),
            Decimal("0"),
        )
        revenue_days = sum(
            1
            for item in stats
            if item.haircuts_count > 0 or item.service_revenue + item.additional_services_revenue > 0
        )
        average_daily = total_revenue / Decimal(revenue_days) if revenue_days else Decimal("0")
        revenue_progress = min(
            Decimal("100"),
            average_daily / rule.average_daily_revenue_required * Decimal("100")
            if rule.average_daily_revenue_required
            else Decimal("100"),
        )
        employment_progress = Decimal("100")
        tenure_months: int | None = None
        if employee.employment_started_at:
            tenure_months = _months_between(employee.employment_started_at, date.today())
            employment_progress = min(
                Decimal("100"),
                Decimal(tenure_months) / Decimal(rule.minimum_employment_months) * Decimal("100"),
            )
        daily_revenue_left = max(Decimal("0"), rule.average_daily_revenue_required - average_daily)
        return GradeProgress(
            service_revenue=total_revenue,
            revenue_days=revenue_days,
            average_daily_revenue=average_daily,
            daily_revenue_left=daily_revenue_left,
            revenue_percent=revenue_progress,
            tenure_months=tenure_months,
            tenure_percent=employment_progress,
            overall_percent=min(revenue_progress, employment_progress),
        )


@dataclass(slots=True)
class GradeProgress:
    service_revenue: Decimal
    revenue_days: int
    average_daily_revenue: Decimal
    daily_revenue_left: Decimal
    revenue_percent: Decimal
    tenure_months: int | None
    tenure_percent: Decimal
    overall_percent: Decimal


def _find_current_and_next(
    rules: list[GradeRule],
    current_category: str | None,
) -> tuple[GradeRule | None, GradeRule | None]:
    if current_category is None:
        return None, rules[0] if rules else None
    for index, rule in enumerate(rules):
        if _rule_matches_category(rule, current_category):
            next_rule = rules[index + 1] if index + 1 < len(rules) else None
            return rule, next_rule
    return None, rules[0] if rules else None


def _grade_period_bounds(months_required: int) -> tuple[date, date]:
    today = date.today()
    year = today.year
    month_number = today.month
    for _ in range(max(0, months_required - 1)):
        month_number -= 1
        if month_number == 0:
            month_number = 12
            year -= 1
    return date(year, month_number, 1), today


def _months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def _tenure_scope(rule: GradeRule) -> str:
    return "комп." if rule.sort_order <= 1 else "кат."


def _tenure_line(tenure_months: int | None, required_months: int) -> str:
    if tenure_months is None:
        return f"нет даты / {required_months} мес."
    return f"{tenure_months} из {required_months} мес."


def _rule_matches_category(rule: GradeRule, current_category: str) -> bool:
    normalized_category = _normalize_grade_text(current_category)
    if normalized_category == _normalize_grade_text(rule.category_title):
        return True
    if str(int(rule.base_price)) in normalized_category:
        return True
    return normalized_category in _aliases_for_price(rule.base_price)


def _rule_display_title(rule: GradeRule) -> str:
    title = _display_title_for_price(rule.base_price) or rule.category_title
    return f"{title} / {money(rule.base_price)}"


def _display_title_for_price(base_price: Decimal) -> str | None:
    return {
        Decimal("1500"): "Мастер",
        Decimal("1700"): "Старший мастер",
        Decimal("1900"): "Эксперт",
        Decimal("2300"): "Старший эксперт",
    }.get(base_price)


def _aliases_for_price(base_price: Decimal) -> set[str]:
    aliases = {
        Decimal("1500"): {"мастер", "барбер"},
        Decimal("1700"): {"старший мастер", "старший барбер"},
        Decimal("1900"): {"эксперт", "топ мастер", "топ барбер"},
        Decimal("2300"): {"старший эксперт", "ведущий эксперт"},
    }
    return aliases.get(base_price, set())


def _normalize_grade_text(value: str) -> str:
    return value.casefold().replace("ё", "е").replace("₽", "").strip()


def progress_bar(progress: Decimal, width: int = 10) -> str:
    filled = int((progress / Decimal("100")) * width)
    return "█" * filled + "░" * (width - filled)
