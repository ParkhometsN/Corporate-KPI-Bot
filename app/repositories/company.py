from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, GradeRule, KpiRule
from app.repositories.base import BaseRepository


class CompanyRepository(BaseRepository[Company]):
    model = Company

    async def get_default(self) -> Company | None:
        result = await self.session.execute(select(Company).order_by(Company.created_at.asc()).limit(1))
        return result.scalar_one_or_none()

    async def get_by_yclients(self, partner_id: int, default_company_id: int) -> Company | None:
        result = await self.session.execute(
            select(Company).where(
                Company.partner_id == partner_id,
                Company.default_company_id == default_company_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_default_company(
        self,
        *,
        title: str,
        partner_id: int,
        default_company_id: int,
        encrypted_api_key: str,
        encrypted_user_token: str | None,
        admin_password_hash: str | None,
        timezone: str,
        synchronization_interval_minutes: int,
    ) -> Company:
        company = await self.get_by_yclients(partner_id, default_company_id)
        if company is None:
            company = Company(
                title=title,
                partner_id=partner_id,
                default_company_id=default_company_id,
                encrypted_yclients_api_key=encrypted_api_key,
                encrypted_yclients_user_token=encrypted_user_token,
                admin_password_hash=admin_password_hash or "",
                timezone=timezone,
                synchronization_interval_minutes=synchronization_interval_minutes,
            )
            self.session.add(company)
        else:
            company.title = title
            company.encrypted_yclients_api_key = encrypted_api_key
            company.encrypted_yclients_user_token = encrypted_user_token
            if admin_password_hash is not None:
                company.admin_password_hash = admin_password_hash
            company.timezone = timezone
            company.synchronization_interval_minutes = synchronization_interval_minutes
        await self.session.flush()
        return company

    async def update_admin_password_hash(self, company: Company, admin_password_hash: str) -> Company:
        company.admin_password_hash = admin_password_hash
        await self.session.flush()
        return company

    async def update_yclients_user_token(self, company: Company, encrypted_user_token: str | None) -> Company:
        company.encrypted_yclients_user_token = encrypted_user_token
        await self.session.flush()
        return company

    async def update_regulation_text(self, company: Company, text: str | None) -> Company:
        company.regulation_text = text
        await self.session.flush()
        return company

    async def save_yclients_partner_setup(
        self,
        *,
        title: str,
        partner_id: int,
        encrypted_api_key: str,
        encrypted_user_token: str | None,
        admin_password_hash: str | None,
        timezone: str,
        synchronization_interval_minutes: int,
    ) -> Company:
        company = await self.get_default()
        if company is None:
            company = Company(
                title=title,
                partner_id=partner_id,
                default_company_id=0,
                encrypted_yclients_api_key=encrypted_api_key,
                encrypted_yclients_user_token=encrypted_user_token,
                admin_password_hash=admin_password_hash or "",
                timezone=timezone,
                synchronization_interval_minutes=synchronization_interval_minutes,
            )
            self.session.add(company)
        else:
            company.title = title
            company.partner_id = partner_id
            company.default_company_id = 0
            company.encrypted_yclients_api_key = encrypted_api_key
            company.encrypted_yclients_user_token = encrypted_user_token
            if admin_password_hash is not None:
                company.admin_password_hash = admin_password_hash
            company.timezone = timezone
            company.synchronization_interval_minutes = synchronization_interval_minutes
        await self.session.flush()
        return company


class KpiRuleRepository(BaseRepository[KpiRule]):
    model = KpiRule

    async def list_active(self, company_id) -> list[KpiRule]:
        result = await self.session.execute(
            select(KpiRule)
            .where(KpiRule.company_id == company_id, KpiRule.is_active.is_(True))
            .order_by(KpiRule.threshold_amount.asc())
        )
        return list(result.scalars().all())

    async def list_by_company(self, company_id) -> list[KpiRule]:
        result = await self.session.execute(
            select(KpiRule)
            .where(KpiRule.company_id == company_id)
            .order_by(KpiRule.threshold_amount.asc())
        )
        return list(result.scalars().all())

    async def replace_rules(self, company_id, rules: list[tuple[Decimal, Decimal]]) -> list[KpiRule]:
        existing = await self.list_by_company(company_id)
        existing_by_threshold = {rule.threshold_amount: rule for rule in existing}
        updated: list[KpiRule] = []
        for threshold, percent in rules:
            rule = existing_by_threshold.get(threshold)
            if rule is None:
                rule = KpiRule(company_id=company_id, threshold_amount=threshold, percent=percent)
                self.session.add(rule)
            else:
                rule.percent = percent
                rule.is_active = True
            updated.append(rule)
        updated_thresholds = {threshold for threshold, _ in rules}
        for rule in existing:
            if rule.threshold_amount not in updated_thresholds:
                rule.is_active = False
        await self.session.flush()
        return updated


class GradeRuleRepository(BaseRepository[GradeRule]):
    model = GradeRule

    async def list_active(self, company_id) -> list[GradeRule]:
        result = await self.session.execute(
            select(GradeRule)
            .where(GradeRule.company_id == company_id, GradeRule.is_active.is_(True))
            .order_by(GradeRule.sort_order.asc())
        )
        return list(result.scalars().all())

    async def list_by_company(self, company_id) -> list[GradeRule]:
        result = await self.session.execute(
            select(GradeRule)
            .where(GradeRule.company_id == company_id)
            .order_by(GradeRule.sort_order.asc())
        )
        return list(result.scalars().all())

    async def replace_rules(
        self,
        company_id,
        rules: list[tuple[str, Decimal, Decimal, int, int]],
    ) -> list[GradeRule]:
        existing = await self.list_by_company(company_id)
        existing_by_title = {rule.category_title.casefold(): rule for rule in existing}
        updated: list[GradeRule] = []
        for index, (title, base_price, average_revenue, months_required, min_months) in enumerate(rules, start=1):
            rule = existing_by_title.get(title.casefold())
            if rule is None:
                rule = GradeRule(
                    company_id=company_id,
                    category_title=title,
                    base_price=base_price,
                    average_daily_revenue_required=average_revenue,
                    months_required=months_required,
                    minimum_employment_months=min_months,
                    sort_order=index,
                )
                self.session.add(rule)
            else:
                rule.base_price = base_price
                rule.average_daily_revenue_required = average_revenue
                rule.months_required = months_required
                rule.minimum_employment_months = min_months
                rule.sort_order = index
                rule.is_active = True
            updated.append(rule)
        active_titles = {title.casefold() for title, *_ in rules}
        for rule in existing:
            if rule.category_title.casefold() not in active_titles:
                rule.is_active = False
        await self.session.flush()
        return updated

    async def ensure_defaults(self, company_id) -> list[GradeRule]:
        existing = await self.list_active(company_id)
        if existing:
            return existing

        defaults = [
            ("Мастер", Decimal("1500"), Decimal("12500"), 2, 6, 1),
            ("Старший мастер", Decimal("1700"), Decimal("14500"), 2, 6, 2),
            ("Эксперт", Decimal("1900"), Decimal("18000"), 3, 12, 3),
            ("Старший эксперт", Decimal("2300"), Decimal("21000"), 3, 12, 4),
        ]
        rules: list[GradeRule] = []
        for title, base_price, avg_revenue, months_required, min_months, order in defaults:
            rule = GradeRule(
                company_id=company_id,
                category_title=title,
                base_price=base_price,
                average_daily_revenue_required=avg_revenue,
                months_required=months_required,
                minimum_employment_months=min_months,
                sort_order=order,
            )
            self.session.add(rule)
            rules.append(rule)
        await self.session.flush()
        return rules
