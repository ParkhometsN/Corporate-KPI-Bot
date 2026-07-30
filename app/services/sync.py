from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.config.settings import Settings
from app.models import Branch, Company, SyncStatus
from app.repositories import (
    BranchRepository,
    CompanyRepository,
    EmployeeRepository,
    ServiceRepository,
)
from app.services.security import EncryptionService
from app.utils.datetime import utc_now_naive
from app.yclients.client import YClientsClient

logger = get_logger(__name__)


class SyncService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._companies = CompanyRepository(session)
        self._branches = BranchRepository(session)
        self._employees = EmployeeRepository(session)
        self._services = ServiceRepository(session)
        self._encryption = EncryptionService(settings)

    async def sync_company(self, company: Company | None = None) -> list[Branch]:
        company = company or await self._companies.get_default()
        if company is None:
            return []
        branches = await self._branches.list_by_company(company.id)
        synced: list[Branch] = []
        for branch in branches:
            await self.sync_branch(branch, company=company)
            synced.append(branch)
        return synced

    async def sync_branch(self, branch: Branch, *, company: Company | None = None) -> Branch:
        company = company or await self._companies.get(branch.company_id)
        if company is None:
            return branch
        client = self._client_for_company(company)
        try:
            employees = await client.list_employees(branch.yclients_branch_id)
            active_staff_ids = {employee.id for employee in employees}
            for employee in employees:
                await self._employees.upsert(
                    branch_id=branch.id,
                    yclients_staff_id=employee.id,
                    full_name=employee.name,
                    specialization=employee.specialization,
                    category_title=employee.category_title,
                )
            inactive_employees = await self._employees.deactivate_missing_staff(branch.id, active_staff_ids)

            services = await client.list_services(branch.yclients_branch_id)
            active_service_ids = {service.id for service in services}
            for service in services:
                await self._services.upsert(
                    branch_id=branch.id,
                    yclients_service_id=service.id,
                    title=service.title,
                    category=service.category,
                    price_min=service.price_min,
                    price_max=service.price_max,
                )
            inactive_services = await self._services.deactivate_missing_services(branch.id, active_service_ids)

            branch.employees_count = len(employees)
            branch.sync_status = SyncStatus.SYNCED
            branch.last_synced_at = utc_now_naive()
            branch.last_sync_error = None
            logger.info(
                "branch_synced",
                branch_id=str(branch.id),
                employees=len(employees),
                inactive_employees=inactive_employees,
                services=len(services),
                inactive_services=inactive_services,
            )
        except Exception as exc:
            await self._branches.mark_sync_error(branch, str(exc))
            logger.exception("branch_sync_failed", branch_id=str(branch.id))
        return branch

    def _client_for_company(self, company: Company) -> YClientsClient:
        partner_token = self._encryption.decrypt(company.encrypted_yclients_api_key)
        user_token = self._encryption.decrypt(company.encrypted_yclients_user_token) or self._settings.yclients_user_token
        return YClientsClient(
            base_url=self._settings.yclients_base_url_str,
            partner_token=partner_token or self._settings.yclients_partner_token,
            user_token=user_token,
            timeout_seconds=self._settings.yclients_timeout_seconds,
        )
