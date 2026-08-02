from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.models import Employee, TelegramUser
from app.repositories.base import BaseRepository


class EmployeeRepository(BaseRepository[Employee]):
    model = Employee

    async def list_by_branch(self, branch_id: UUID) -> list[Employee]:
        result = await self.session.execute(
            select(Employee)
            .where(Employee.branch_id == branch_id, Employee.is_active.is_(True))
            .options(selectinload(Employee.branch), selectinload(Employee.telegram_user))
            .order_by(Employee.full_name.asc())
        )
        return list(result.scalars().all())

    async def list_active(self, limit: int = 300) -> list[Employee]:
        result = await self.session.execute(
            select(Employee)
            .where(Employee.is_active.is_(True))
            .options(selectinload(Employee.branch), selectinload(Employee.telegram_user))
            .order_by(Employee.full_name.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_related_active(self, employee: Employee) -> list[Employee]:
        normalized_name = employee.full_name.strip().casefold()
        result = await self.session.execute(
            select(Employee)
            .where(
                Employee.is_active.is_(True),
                or_(
                    Employee.yclients_staff_id == employee.yclients_staff_id,
                    func.lower(Employee.full_name) == normalized_name,
                ),
            )
            .options(selectinload(Employee.branch), selectinload(Employee.telegram_user))
            .order_by(Employee.full_name.asc())
        )
        employees = list(result.scalars().all())
        return sorted(employees, key=lambda item: ((item.branch.name if item.branch else ""), item.full_name))

    async def get_full(self, employee_id: UUID) -> Employee | None:
        result = await self.session.execute(
            select(Employee)
            .where(Employee.id == employee_id)
            .options(selectinload(Employee.branch), selectinload(Employee.telegram_user))
        )
        return result.scalar_one_or_none()

    async def get_by_staff_id(self, branch_id: UUID, yclients_staff_id: int) -> Employee | None:
        result = await self.session.execute(
            select(Employee).where(
                Employee.branch_id == branch_id,
                Employee.yclients_staff_id == yclients_staff_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_telegram_id(self, telegram_id: int) -> Employee | None:
        result = await self.session.execute(
            select(Employee)
            .join(TelegramUser, Employee.telegram_user_id == TelegramUser.id)
            .where(TelegramUser.telegram_id == telegram_id, Employee.is_active.is_(True))
            .options(selectinload(Employee.branch), selectinload(Employee.telegram_user))
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        branch_id: UUID,
        yclients_staff_id: int,
        full_name: str,
        specialization: str | None,
        category_title: str | None,
    ) -> Employee:
        employee = await self.get_by_staff_id(branch_id, yclients_staff_id)
        if employee is None:
            employee = Employee(
                branch_id=branch_id,
                yclients_staff_id=yclients_staff_id,
                full_name=full_name,
                specialization=specialization,
                category_title=category_title,
            )
            self.session.add(employee)
        else:
            employee.full_name = full_name
            employee.specialization = specialization
            employee.category_title = category_title
            employee.is_active = True
        employee.last_synced_at = datetime.now()
        await self.session.flush()
        return employee

    async def attach_telegram(self, employee: Employee, telegram_user_id: UUID) -> Employee:
        employee.telegram_user_id = telegram_user_id
        employee.connected_at = datetime.now()
        await self.session.flush()
        return employee

    async def detach_telegram(self, employee: Employee) -> Employee:
        employee.telegram_user_id = None
        employee.connected_at = None
        await self.session.flush()
        return employee

    async def deactivate_missing_staff(self, branch_id: UUID, active_staff_ids: set[int]) -> int:
        statement = select(Employee).where(Employee.branch_id == branch_id, Employee.is_active.is_(True))
        if active_staff_ids:
            statement = statement.where(Employee.yclients_staff_id.not_in(active_staff_ids))
        result = await self.session.execute(statement)
        missing_employees = list(result.scalars().all())
        for employee in missing_employees:
            employee.is_active = False
            employee.telegram_user_id = None
            employee.connected_at = None
            employee.last_synced_at = datetime.now()
        await self.session.flush()
        return len(missing_employees)
