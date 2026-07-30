from sqlalchemy import delete, select

from app.models import NotificationSettings, Role, TelegramUser
from app.repositories.base import BaseRepository


class TelegramUserRepository(BaseRepository[TelegramUser]):
    model = TelegramUser

    async def get_by_telegram_id(self, telegram_id: int) -> TelegramUser | None:
        result = await self.session.execute(
            select(TelegramUser).where(TelegramUser.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def has_active_admins(self) -> bool:
        result = await self.session.execute(
            select(TelegramUser.id)
            .where(TelegramUser.role == Role.ADMIN, TelegramUser.is_active.is_(True))
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def upsert(
        self,
        *,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        role: Role | None = None,
    ) -> TelegramUser:
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            user = TelegramUser(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                role=role or Role.EMPLOYEE,
            )
            self.session.add(user)
            await self.session.flush()
            self.session.add(NotificationSettings(telegram_user_id=user.id))
        else:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            if role is not None:
                user.role = role
        await self.session.flush()
        return user

    async def delete_employee_users(self) -> int:
        result = await self.session.execute(delete(TelegramUser).where(TelegramUser.role == Role.EMPLOYEE))
        await self.session.flush()
        return result.rowcount or 0

    async def delete_all_users(self) -> int:
        result = await self.session.execute(delete(TelegramUser))
        await self.session.flush()
        return result.rowcount or 0
