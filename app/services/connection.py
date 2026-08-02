from datetime import timedelta
from dataclasses import dataclass
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


@dataclass(slots=True)
class ConnectionAdminMessage:
    chat_id: int
    message_id: int


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

    async def attach_code_admin_message(self, code: str, *, chat_id: int, message_id: int) -> None:
        connection_code = await self._get_code_by_plain_value(code)
        if connection_code is None:
            return
        connection_code.admin_chat_id = chat_id
        connection_code.admin_message_id = message_id
        await self._session.flush()

    async def admin_message_for_code(self, code: str) -> ConnectionAdminMessage | None:
        connection_code = await self._get_code_by_plain_value(code)
        if connection_code is None or connection_code.admin_chat_id is None or connection_code.admin_message_id is None:
            return None
        return ConnectionAdminMessage(chat_id=connection_code.admin_chat_id, message_id=connection_code.admin_message_id)

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

    async def _get_code_by_plain_value(self, code: str) -> ConnectionCode | None:
        code_hash = self._code_hashes.hash_code(code)
        result = await self._session.execute(
            select(ConnectionCode)
            .where(ConnectionCode.code_hash == code_hash)
            .order_by(ConnectionCode.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_employee_by_telegram_id(self, telegram_id: int) -> Employee | None:
        return await self._employees.get_by_telegram_id(telegram_id)

    async def get_employee(self, employee_id) -> Employee | None:
        return await self._employees.get_full(employee_id)

    async def get_related_employees(self, employee: Employee) -> list[Employee]:
        return await self._employees.list_related_active(employee)

    async def disconnect_employee(self, employee_id) -> Employee:
        employee = await self._employees.get(employee_id)
        if employee is None:
            raise EntityNotFoundError("Сотрудник не найден.")
        return await self._employees.detach_telegram(employee)

    @staticmethod
    def _generate_plain_code() -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(8))
