from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import Branch, SyncStatus
from app.repositories.base import BaseRepository


class BranchRepository(BaseRepository[Branch]):
    model = Branch

    async def list_by_company(self, company_id: UUID) -> list[Branch]:
        result = await self.session.execute(
            select(Branch)
            .where(Branch.company_id == company_id)
            .options(selectinload(Branch.employees))
            .order_by(Branch.name.asc())
        )
        return list(result.scalars().all())

    async def list_owned_by_user(self, company_id: UUID, owner_telegram_user_id: UUID) -> list[Branch]:
        result = await self.session.execute(
            select(Branch)
            .where(Branch.company_id == company_id, Branch.owner_telegram_user_id == owner_telegram_user_id)
            .options(selectinload(Branch.employees))
            .order_by(Branch.name.asc())
        )
        return list(result.scalars().all())

    async def get_by_yclients_id(self, company_id: UUID, yclients_branch_id: int) -> Branch | None:
        result = await self.session.execute(
            select(Branch).where(
                Branch.company_id == company_id,
                Branch.yclients_branch_id == yclients_branch_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        company_id: UUID,
        owner_telegram_user_id: UUID | None = None,
        yclients_branch_id: int,
        name: str,
        address: str | None,
        sync_status: SyncStatus = SyncStatus.SYNCED,
        last_synced_at: datetime | None = None,
    ) -> Branch:
        branch = await self.get_by_yclients_id(company_id, yclients_branch_id)
        if branch is None:
            branch = Branch(
                company_id=company_id,
                owner_telegram_user_id=owner_telegram_user_id,
                yclients_branch_id=yclients_branch_id,
                name=name,
                address=address,
                sync_status=sync_status,
                last_synced_at=last_synced_at,
            )
            self.session.add(branch)
        else:
            branch.name = name
            branch.address = address
            if owner_telegram_user_id is not None and branch.owner_telegram_user_id is None:
                branch.owner_telegram_user_id = owner_telegram_user_id
            branch.sync_status = sync_status
            branch.last_synced_at = last_synced_at
            branch.last_sync_error = None
        await self.session.flush()
        return branch

    async def mark_sync_error(self, branch: Branch, error: str) -> None:
        branch.sync_status = SyncStatus.ERROR
        branch.last_sync_error = error[:1000]
        await self.session.flush()

    async def delete_branch(self, branch: Branch) -> None:
        await self.session.delete(branch)
        await self.session.flush()

    async def delete_legacy_seed_branch(self, company_id: UUID, yclients_branch_id: int) -> bool:
        result = await self.session.execute(
            select(Branch).where(
                Branch.company_id == company_id,
                Branch.yclients_branch_id == yclients_branch_id,
                Branch.sync_status == SyncStatus.NEW,
                Branch.employees_count == 0,
                Branch.last_synced_at.is_(None),
            )
        )
        branch = result.scalar_one_or_none()
        if branch is None:
            return False
        await self.session.delete(branch)
        await self.session.flush()
        return True
