from datetime import timedelta
import secrets

from aiogram.types import User as TelegramProfile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.models import ConnectionCode, ConnectionCodeStatus, Employee, Role
from app.repositories import EmployeeRepository, TelegramUserRepository
from app.services.security import CodeHashService
from app.utils.datetime import utc_now_naive
from app.utils.exceptions import EntityNotFoundError, ValidationError


class EmployeeConnectionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._employees = EmployeeRepository(session)
        self._telegram_users = TelegramUserRepository(session)
        self._code_hashes = CodeHashService(settings)

    async def generate_code(self, employee_id) -> str:
        employee = await self._employees.get(employee_id)
        if employee is None:
            raise EntityNotFoundError("Сотрудник не найден.")
        code = self._generate_plain_code()
        connection_code = ConnectionCode(
            employee_id=employee.id,
            code_hash=self._code_hashes.hash_code(code),
            expires_at=utc_now_naive() + timedelta(minutes=self._settings.connection_code_ttl_minutes),
        )
        self._session.add(connection_code)
        await self._session.flush()
        return code

    async def bind_employee(self, profile: TelegramProfile, code: str) -> Employee:
        code_hash = self._code_hashes.hash_code(code)
        now = utc_now_naive()
        result = await self._session.execute(
            select(ConnectionCode, Employee)
            .join(Employee, ConnectionCode.employee_id == Employee.id)
            .where(
                ConnectionCode.code_hash == code_hash,
                ConnectionCode.status == ConnectionCodeStatus.ACTIVE,
                Employee.is_active.is_(True),
            )
        )
        row = result.first()
        if row is None:
            raise ValidationError("Код не найден или уже использован.")
        connection_code, employee = row
        if connection_code.expires_at < now:
            connection_code.status = ConnectionCodeStatus.EXPIRED
            await self._session.flush()
            raise ValidationError("Срок действия кода истёк. Запросите новый код у руководителя.")

        telegram_user = await self._telegram_users.upsert(
            telegram_id=profile.id,
            username=profile.username,
            first_name=profile.first_name,
            last_name=profile.last_name,
            role=Role.EMPLOYEE,
        )
        await self._employees.attach_telegram(employee, telegram_user.id)
        connection_code.status = ConnectionCodeStatus.USED
        connection_code.used_at = now
        await self._session.flush()
        return employee

    async def get_employee_by_telegram_id(self, telegram_id: int) -> Employee | None:
        return await self._employees.get_by_telegram_id(telegram_id)

    async def disconnect_employee(self, employee_id) -> Employee:
        employee = await self._employees.get(employee_id)
        if employee is None:
            raise EntityNotFoundError("Сотрудник не найден.")
        return await self._employees.detach_telegram(employee)

    @staticmethod
    def _generate_plain_code() -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(8))
