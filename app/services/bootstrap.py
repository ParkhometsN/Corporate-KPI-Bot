from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.repositories import (
    BranchRepository,
    CompanyRepository,
    GradeRuleRepository,
    KpiRuleRepository,
    TelegramUserRepository,
)
from app.services.security import EncryptionService, PasswordService


class BootstrapService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._companies = CompanyRepository(session)
        self._branches = BranchRepository(session)
        self._kpi_rules = KpiRuleRepository(session)
        self._grade_rules = GradeRuleRepository(session)
        self._telegram_users = TelegramUserRepository(session)
        self._encryption = EncryptionService(settings)
        self._passwords = PasswordService()

    async def ensure_default_setup(self) -> None:
        existing_company = await self._companies.get_default()
        admin_password_hash = (
            existing_company.admin_password_hash
            if existing_company is not None and existing_company.admin_password_hash
            else self._passwords.hash_password(self._settings.admin_password)
        )
        should_reset_legacy_seed = (
            existing_company is not None
            and not await self._telegram_users.has_active_admins()
            and existing_company.default_company_id == self._settings.yclients_default_company_id
            and existing_company.title == self._settings.default_company_title
        )
        is_not_configured = existing_company is None or should_reset_legacy_seed
        encrypted_api_key = (
            self._encryption.encrypt("") or ""
            if is_not_configured
            else existing_company.encrypted_yclients_api_key
        )
        encrypted_user_token = (
            None if is_not_configured else existing_company.encrypted_yclients_user_token
        )
        company = await self._companies.save_yclients_partner_setup(
            title="Компания не настроена" if is_not_configured else existing_company.title,
            partner_id=0 if is_not_configured else existing_company.partner_id,
            encrypted_api_key=encrypted_api_key,
            encrypted_user_token=encrypted_user_token,
            admin_password_hash=admin_password_hash,
            timezone=self._settings.timezone,
            synchronization_interval_minutes=self._settings.sync_interval_minutes,
        )
        if should_reset_legacy_seed:
            await self._branches.delete_legacy_seed_branch(
                company.id,
                self._settings.yclients_default_company_id,
            )
        await self._branches.delete_legacy_seed_branch(
            company.id,
            self._settings.yclients_default_company_id,
        )
        await self._kpi_rules.replace_rules(
            company.id,
            [
                (Decimal("0"), Decimal("0")),
                (Decimal("37000"), Decimal("2")),
                (Decimal("60000"), Decimal("5")),
            ],
        )
        await self._grade_rules.ensure_defaults(company.id)
        await self._session.flush()
