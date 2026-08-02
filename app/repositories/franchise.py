from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import FranchiseBranchAccess, FranchiseInvite, Franchisee, TelegramUser
from app.repositories.base import BaseRepository


class FranchiseeRepository(BaseRepository[Franchisee]):
    model = Franchisee

    async def get_full(self, franchisee_id: UUID) -> Franchisee | None:
        result = await self.session.execute(
            select(Franchisee)
            .where(Franchisee.id == franchisee_id)
            .options(
                selectinload(Franchisee.telegram_user),
                selectinload(Franchisee.branch_accesses).selectinload(FranchiseBranchAccess.branch),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_telegram_user_id(self, telegram_user_id: UUID) -> Franchisee | None:
        result = await self.session.execute(
            select(Franchisee)
            .where(Franchisee.telegram_user_id == telegram_user_id)
            .options(
                selectinload(Franchisee.telegram_user),
                selectinload(Franchisee.branch_accesses).selectinload(FranchiseBranchAccess.branch),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_telegram_id(self, telegram_id: int) -> Franchisee | None:
        result = await self.session.execute(
            select(Franchisee)
            .join(TelegramUser, Franchisee.telegram_user_id == TelegramUser.id)
            .where(TelegramUser.telegram_id == telegram_id)
            .options(
                selectinload(Franchisee.telegram_user),
                selectinload(Franchisee.branch_accesses).selectinload(FranchiseBranchAccess.branch),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_company(self, company_id: UUID) -> list[Franchisee]:
        result = await self.session.execute(
            select(Franchisee)
            .where(Franchisee.company_id == company_id)
            .options(
                selectinload(Franchisee.telegram_user),
                selectinload(Franchisee.branch_accesses).selectinload(FranchiseBranchAccess.branch),
            )
            .order_by(Franchisee.created_at.desc())
        )
        return list(result.scalars().all())

    async def upsert_connected(
        self,
        *,
        company_id: UUID,
        telegram_user_id: UUID,
        created_by_user_id: UUID | None,
        title: str,
    ) -> Franchisee:
        franchisee = await self.get_by_telegram_user_id(telegram_user_id)
        if franchisee is None:
            franchisee = Franchisee(
                company_id=company_id,
                telegram_user_id=telegram_user_id,
                created_by_user_id=created_by_user_id,
                title=title,
                connected_at=datetime.now(),
            )
            self.session.add(franchisee)
        else:
            franchisee.title = title
            franchisee.is_blocked = False
            franchisee.blocked_at = None
            franchisee.blocked_reason = None
            franchisee.connected_at = franchisee.connected_at or datetime.now()
        await self.session.flush()
        return franchisee

    async def set_blocked(self, franchisee: Franchisee, blocked: bool, *, reason: str | None = None) -> Franchisee:
        franchisee.is_blocked = blocked
        franchisee.blocked_at = datetime.now() if blocked else None
        franchisee.blocked_reason = reason if blocked else None
        await self.session.flush()
        return franchisee

    async def update_yclients_user_token(self, franchisee: Franchisee, encrypted_user_token: str | None) -> Franchisee:
        franchisee.encrypted_yclients_user_token = encrypted_user_token
        await self.session.flush()
        return franchisee

    async def update_global_permissions(
        self,
        franchisee: Franchisee,
        *,
        can_view_owner_branches: bool | None = None,
        can_message_owner_employees: bool | None = None,
        can_receive_owner_statistics: bool | None = None,
    ) -> Franchisee:
        if can_view_owner_branches is not None:
            franchisee.can_view_owner_branches = can_view_owner_branches
        if can_message_owner_employees is not None:
            franchisee.can_message_owner_employees = can_message_owner_employees
        if can_receive_owner_statistics is not None:
            franchisee.can_receive_owner_statistics = can_receive_owner_statistics
        await self.session.flush()
        return franchisee


class FranchiseInviteRepository(BaseRepository[FranchiseInvite]):
    model = FranchiseInvite

    async def get_active_by_hash(self, code_hash: str) -> FranchiseInvite | None:
        result = await self.session.execute(
            select(FranchiseInvite)
            .where(FranchiseInvite.code_hash == code_hash, FranchiseInvite.status == "active")
            .options(selectinload(FranchiseInvite.franchisee))
        )
        return result.scalar_one_or_none()

    async def get_by_hash(self, code_hash: str) -> FranchiseInvite | None:
        result = await self.session.execute(
            select(FranchiseInvite)
            .where(FranchiseInvite.code_hash == code_hash)
            .options(selectinload(FranchiseInvite.franchisee))
            .order_by(FranchiseInvite.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


class FranchiseBranchAccessRepository(BaseRepository[FranchiseBranchAccess]):
    model = FranchiseBranchAccess

    async def get_for_pair(self, franchisee_id: UUID, branch_id: UUID) -> FranchiseBranchAccess | None:
        result = await self.session.execute(
            select(FranchiseBranchAccess).where(
                FranchiseBranchAccess.franchisee_id == franchisee_id,
                FranchiseBranchAccess.branch_id == branch_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        franchisee_id: UUID,
        branch_id: UUID,
        can_view_statistics: bool,
        can_message_employees: bool,
        can_manage_employees: bool,
    ) -> FranchiseBranchAccess:
        access = await self.get_for_pair(franchisee_id, branch_id)
        if access is None:
            access = FranchiseBranchAccess(
                franchisee_id=franchisee_id,
                branch_id=branch_id,
                can_view_statistics=can_view_statistics,
                can_message_employees=can_message_employees,
                can_manage_employees=can_manage_employees,
            )
            self.session.add(access)
        else:
            access.can_view_statistics = can_view_statistics
            access.can_message_employees = can_message_employees
            access.can_manage_employees = can_manage_employees
            access.is_active = True
        await self.session.flush()
        return access
