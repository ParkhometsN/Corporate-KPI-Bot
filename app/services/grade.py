from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.models import Employee, GradeRule
from app.repositories import CompanyRepository, GradeRuleRepository, MonthlyStatisticRepository
from app.services.statistics import money
from app.utils.telegram_formatting import blockquote, bold, pre, progress_bar as telegram_progress_bar


class GradeService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._companies = CompanyRepository(session)
        self._grade_rules = GradeRuleRepository(session)
        self._monthly_stats = MonthlyStatisticRepository(session)

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
        if current_rule is None:
            current_rule = rules[0]
            next_rule = rules[1] if len(rules) > 1 else None
        if next_rule is None:
            return "\n\n".join(
                [
                    bold("GRADE UP"),
                    pre(
                        [
                            f"Сотрудник  {employee.full_name}",
                            f"Категория  {current_rule.category_title}",
                        ]
                    ),
                    blockquote("Вы уже на максимальной категории."),
                ]
            )

        progress = await self._calculate_progress(employee, next_rule)
        return "\n\n".join(
            [
                bold("GRADE UP"),
                pre(
                    [
                        f"Сотрудник   {employee.full_name}",
                        f"Сейчас      {current_rule.category_title}",
                        f"Следующий   {next_rule.category_title}",
                        f"Выручка/дн. {money(next_rule.average_daily_revenue_required)}",
                        f"Период      {next_rule.months_required} мес.",
                        f"Стаж        {next_rule.minimum_employment_months} мес.",
                        f"Прогресс    {telegram_progress_bar(progress)} {progress:.0f}%",
                    ]
                ),
                blockquote("Прогресс считается по средней дневной выручке и минимальному стажу для следующей категории."),
            ]
        )

    async def _calculate_progress(self, employee: Employee, rule: GradeRule) -> Decimal:
        month = date.today().replace(day=1)
        checked_months = []
        year = month.year
        month_number = month.month
        for _ in range(rule.months_required):
            month_number -= 1
            if month_number == 0:
                month_number = 12
                year -= 1
            checked_months.append(date(year, month_number, 1))

        total_revenue = Decimal("0")
        days = Decimal("0")
        for stat_month in checked_months:
            stat = await self._monthly_stats.get_for_employee(employee.id, stat_month)
            if stat:
                total_revenue += stat.service_revenue + stat.additional_services_revenue
                days += Decimal("30")

        average_daily = total_revenue / days if days else Decimal("0")
        revenue_progress = min(
            Decimal("100"),
            average_daily / rule.average_daily_revenue_required * Decimal("100")
            if rule.average_daily_revenue_required
            else Decimal("100"),
        )
        employment_progress = Decimal("100")
        if employee.employment_started_at:
            months = (date.today().year - employee.employment_started_at.year) * 12 + (
                date.today().month - employee.employment_started_at.month
            )
            employment_progress = min(
                Decimal("100"),
                Decimal(months) / Decimal(rule.minimum_employment_months) * Decimal("100"),
            )
        return min(revenue_progress, employment_progress)


def _find_current_and_next(
    rules: list[GradeRule],
    current_category: str | None,
) -> tuple[GradeRule | None, GradeRule | None]:
    if current_category is None:
        return None, rules[0] if rules else None
    for index, rule in enumerate(rules):
        if rule.category_title == current_category:
            next_rule = rules[index + 1] if index + 1 < len(rules) else None
            return rule, next_rule
    return None, rules[0] if rules else None


def progress_bar(progress: Decimal, width: int = 10) -> str:
    filled = int((progress / Decimal("100")) * width)
    return "█" * filled + "░" * (width - filled)
