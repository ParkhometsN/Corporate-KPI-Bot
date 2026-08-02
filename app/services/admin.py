from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
import re
import secrets
from uuid import UUID

from aiogram.types import User as TelegramProfile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.config.settings import Settings
from app.models import Branch, Company, Employee, FranchiseInvite, Franchisee, Role, TelegramUser
from app.repositories import (
    BranchRepository,
    CompanyRepository,
    EmployeeRepository,
    FranchiseBranchAccessRepository,
    FranchiseInviteRepository,
    FranchiseeRepository,
    GradeRuleRepository,
    KpiRuleRepository,
    ServiceRepository,
    TelegramUserRepository,
)
from app.services.security import CodeHashService, EncryptionService, PasswordService
from app.services.sync import SyncService
from app.utils.datetime import utc_now_naive
from app.utils.telegram_formatting import blockquote, bold, money, pre
from app.utils.exceptions import AccessDeniedError, EntityNotFoundError, ValidationError
from app.yclients.client import YClientsClient
from app.yclients.types import YClientsBranch

logger = get_logger(__name__)


@dataclass(slots=True)
class AdminMessageRef:
    chat_id: int
    message_id: int


class AdminService:
    def __init__(self, session: AsyncSession, settings: Settings, sync_service: SyncService) -> None:
        self._session = session
        self._settings = settings
        self._companies = CompanyRepository(session)
        self._branches = BranchRepository(session)
        self._employees = EmployeeRepository(session)
        self._services = ServiceRepository(session)
        self._franchisees = FranchiseeRepository(session)
        self._franchise_invites = FranchiseInviteRepository(session)
        self._franchise_accesses = FranchiseBranchAccessRepository(session)
        self._kpi_rules = KpiRuleRepository(session)
        self._grade_rules = GradeRuleRepository(session)
        self._telegram_users = TelegramUserRepository(session)
        self._code_hashes = CodeHashService(settings)
        self._passwords = PasswordService()
        self._encryption = EncryptionService(settings)
        self._sync = sync_service

    async def authenticate(self, profile: TelegramProfile, password: str) -> TelegramUser:
        company = await self._require_company()
        if not self._passwords.verify_password(password, company.admin_password_hash):
            raise AccessDeniedError("Неверный пароль руководителя.")
        return await self._telegram_users.upsert(
            telegram_id=profile.id,
            username=profile.username,
            first_name=profile.first_name,
            last_name=profile.last_name,
            role=Role.ADMIN,
        )

    async def grant_developer_admin(self, profile: TelegramProfile) -> TelegramUser:
        return await self._telegram_users.upsert(
            telegram_id=profile.id,
            username=profile.username,
            first_name=profile.first_name,
            last_name=profile.last_name,
            role=Role.ADMIN,
        )

    async def has_registered_admins(self) -> bool:
        return await self._telegram_users.has_active_admins()

    async def is_admin(self, telegram_id: int) -> bool:
        user = await self._telegram_users.get_by_telegram_id(telegram_id)
        return bool(user and user.role == Role.ADMIN and user.is_active)

    async def is_manager(self, telegram_id: int) -> bool:
        user = await self._telegram_users.get_by_telegram_id(telegram_id)
        if user is None or not user.is_active:
            return False
        if user.role == Role.ADMIN:
            return True
        if user.role != Role.FRANCHISEE:
            return False
        franchisee = await self._franchisees.get_by_telegram_user_id(user.id)
        return bool(franchisee and not franchisee.is_blocked)

    async def is_yclients_configured(self) -> bool:
        company = await self._companies.get_default()
        return bool(company and self._company_has_yclients_credentials(company))

    async def register_initial_admin(self, profile: TelegramProfile, password: str) -> TelegramUser:
        if await self.has_registered_admins():
            raise AccessDeniedError("Руководитель уже зарегистрирован. Войдите по паролю.")
        if len(password.strip()) < 8:
            raise AccessDeniedError("Пароль должен быть не короче 8 символов.")
        company = await self._require_company()
        await self._companies.update_admin_password_hash(
            company,
            self._passwords.hash_password(password.strip()),
        )
        return await self._telegram_users.upsert(
            telegram_id=profile.id,
            username=profile.username,
            first_name=profile.first_name,
            last_name=profile.last_name,
            role=Role.ADMIN,
        )

    async def get_company(self) -> Company:
        return await self._require_company()

    async def list_branches(self) -> list[Branch]:
        company = await self._require_company()
        return await self._branches.list_by_company(company.id)

    async def list_visible_branches(self, telegram_id: int) -> list[Branch]:
        user = await self.ensure_manager(telegram_id)
        company = await self._require_company()
        if user.role == Role.ADMIN:
            return await self._branches.list_by_company(company.id)
        franchisee = await self._require_franchisee(user)
        owned = await self._branches.list_owned_by_user(company.id, user.id)
        owner_branches = (
            [
                branch
                for branch in await self._branches.list_by_company(company.id)
                if branch.owner_telegram_user_id is None
            ]
            if franchisee.can_view_owner_branches
            else []
        )
        accessed = [
            access.branch
            for access in franchisee.branch_accesses
            if access.is_active
            and access.branch is not None
            and (
                access.can_view_statistics
                or access.can_message_employees
                or access.can_manage_employees
            )
        ]
        by_id = {branch.id: branch for branch in [*owned, *owner_branches, *accessed]}
        return sorted(by_id.values(), key=lambda branch: branch.name)

    async def add_branch(self, yclients_branch_id: int, *, created_by_telegram_id: int | None = None) -> Branch:
        company = await self._require_company()
        if not self._company_has_yclients_credentials(company):
            raise EntityNotFoundError("Сначала укажите YCLIENTS API key и Partner ID.")
        owner_user_id = None
        actor: TelegramUser | None = None
        if created_by_telegram_id is not None:
            actor = await self.ensure_manager(created_by_telegram_id)
            if actor.role == Role.FRANCHISEE:
                owner_user_id = actor.id
        client = await self._client_for_actor(company, actor)
        remote_branch = await client.get_company(yclients_branch_id)
        branch = await self._branches.upsert(
            company_id=company.id,
            owner_telegram_user_id=owner_user_id,
            yclients_branch_id=remote_branch.id,
            name=remote_branch.title,
            address=remote_branch.address,
        )
        await self._sync.sync_branch(branch, company=company, client=client)
        return branch

    async def get_branch(self, branch_id: UUID) -> Branch:
        branch = await self._branches.get(branch_id)
        if branch is None:
            raise EntityNotFoundError("Филиал не найден.")
        return branch

    async def get_visible_branch(self, branch_id: UUID, telegram_id: int) -> Branch:
        branch = await self.get_branch(branch_id)
        user = await self.ensure_manager(telegram_id)
        if user.role == Role.ADMIN:
            return branch
        franchisee = await self._require_franchisee(user)
        if branch.owner_telegram_user_id == user.id:
            return branch
        if franchisee.can_view_owner_branches and branch.owner_telegram_user_id is None:
            return branch
        for access in franchisee.branch_accesses:
            if (
                access.branch_id == branch.id
                and access.is_active
                and (
                    access.can_view_statistics
                    or access.can_message_employees
                    or access.can_manage_employees
                )
            ):
                return branch
        raise AccessDeniedError("Нет доступа к этому филиалу.")

    async def ensure_can_delete_branch(self, branch_id: UUID, telegram_id: int) -> Branch:
        branch = await self.get_visible_branch(branch_id, telegram_id)
        user = await self.ensure_manager(telegram_id)
        if user.role == Role.ADMIN or branch.owner_telegram_user_id == user.id:
            return branch
        raise AccessDeniedError("Руководитель филиала может удалить только свой филиал.")

    async def delete_branch(self, branch_id: UUID) -> Branch:
        branch = await self.get_branch(branch_id)
        await self._branches.delete_branch(branch)
        return branch

    async def get_branch_employees(self, branch_id: UUID):
        return await self._employees.list_by_branch(branch_id)

    async def get_team_employees(self) -> list[Employee]:
        employees: list[Employee] = []
        for branch in await self.list_branches():
            employees.extend(await self._employees.list_by_branch(branch.id))
        return employees

    async def list_active_employees(self) -> list[Employee]:
        return await self._employees.list_active()

    async def get_visible_team_employees(self, telegram_id: int) -> list[Employee]:
        employees: list[Employee] = []
        for branch in await self.list_visible_branches(telegram_id):
            employees.extend(await self._employees.list_by_branch(branch.id))
        return employees

    async def get_broadcast_targets(self, branch_id: UUID | None = None) -> list[Employee]:
        if branch_id is not None:
            employees = await self._employees.list_by_branch(branch_id)
        else:
            employees = await self.get_team_employees()
        return [
            employee
            for employee in employees
            if employee.telegram_user_id and employee.telegram_user and employee.telegram_user.is_active
        ]

    async def get_visible_broadcast_targets(self, telegram_id: int, branch_id: UUID | None = None) -> list[Employee]:
        user = await self.ensure_manager(telegram_id)
        if user.role == Role.ADMIN:
            return await self.get_broadcast_targets(branch_id)
        franchisee = await self._require_franchisee(user)
        branches = [await self.get_visible_branch(branch_id, telegram_id)] if branch_id else await self.list_visible_branches(telegram_id)
        allowed_branch_ids = {
            branch.id
            for branch in branches
            if branch.owner_telegram_user_id == user.id
            or (franchisee.can_message_owner_employees and branch.owner_telegram_user_id is None)
            or any(
                access.branch_id == branch.id
                and access.is_active
                and access.can_message_employees
                for access in franchisee.branch_accesses
            )
        }
        employees: list[Employee] = []
        for visible_branch_id in allowed_branch_ids:
            employees.extend(await self.get_broadcast_targets(visible_branch_id))
        return employees


    async def get_employee(self, employee_id: UUID) -> Employee:
        employee = await self._employees.get_full(employee_id)
        if employee is None:
            raise EntityNotFoundError("Сотрудник не найден.")
        return employee

    async def get_visible_employee(self, employee_id: UUID, telegram_id: int) -> Employee:
        employee = await self.get_employee(employee_id)
        await self.get_visible_branch(employee.branch_id, telegram_id)
        return employee

    async def ensure_admin(self, telegram_id: int) -> TelegramUser:
        user = await self._telegram_users.get_by_telegram_id(telegram_id)
        if user is None or user.role != Role.ADMIN or not user.is_active:
            raise AccessDeniedError("Сначала войдите через /admin.")
        return user

    async def ensure_manager(self, telegram_id: int) -> TelegramUser:
        user = await self._telegram_users.get_by_telegram_id(telegram_id)
        if user is None or not user.is_active or user.role not in {Role.ADMIN, Role.FRANCHISEE}:
            raise AccessDeniedError("Сначала войдите через /admin.")
        if user.role == Role.FRANCHISEE:
            franchisee = await self._franchisees.get_by_telegram_user_id(user.id)
            if franchisee is None or franchisee.is_blocked:
                raise AccessDeniedError("Доступ руководителя филиала заблокирован.")
        return user

    async def generate_franchise_invite(self, created_by_telegram_id: int) -> str:
        created_by = await self.ensure_admin(created_by_telegram_id)
        company = await self._require_company()
        code = "fr_" + _generate_plain_code(14)
        invite = FranchiseInvite(
            company_id=company.id,
            code_hash=self._code_hashes.hash_code(code),
            expires_at=utc_now_naive() + timedelta(days=7),
            created_by_user_id=created_by.id,
        )
        self._session.add(invite)
        await self._session.flush()
        return code

    async def bind_franchisee(self, profile: TelegramProfile, code: str) -> Franchisee:
        invite = await self._franchise_invites.get_active_by_hash(self._code_hashes.hash_code(code))
        now = utc_now_naive()
        if invite is None:
            raise ValidationError("Ссылка руководителя филиала не найдена или уже использована.")
        if invite.expires_at < now:
            invite.status = "expired"
            await self._session.flush()
            raise ValidationError("Срок действия ссылки истёк. Попросите руководителя создать новую.")
        telegram_user = await self._telegram_users.upsert(
            telegram_id=profile.id,
            username=profile.username,
            first_name=profile.first_name,
            last_name=profile.last_name,
            role=Role.FRANCHISEE,
        )
        franchisee = await self._franchisees.upsert_connected(
            company_id=invite.company_id,
            telegram_user_id=telegram_user.id,
            created_by_user_id=invite.created_by_user_id,
            title=_profile_title(profile),
        )
        invite.franchisee_id = franchisee.id
        invite.status = "used"
        invite.used_at = now
        await self._session.flush()
        return franchisee

    async def attach_franchise_invite_message(self, code: str, *, chat_id: int, message_id: int) -> None:
        invite = await self._franchise_invites.get_by_hash(self._code_hashes.hash_code(code))
        if invite is None:
            return
        invite.admin_chat_id = chat_id
        invite.admin_message_id = message_id
        await self._session.flush()

    async def franchise_invite_admin_message(self, code: str) -> AdminMessageRef | None:
        invite = await self._franchise_invites.get_by_hash(self._code_hashes.hash_code(code))
        if invite is None or invite.admin_chat_id is None or invite.admin_message_id is None:
            return None
        return AdminMessageRef(chat_id=invite.admin_chat_id, message_id=invite.admin_message_id)

    async def list_franchisees(self) -> list[Franchisee]:
        company = await self._require_company()
        return await self._franchisees.list_by_company(company.id)

    async def get_franchisee(self, franchisee_id: UUID) -> Franchisee:
        franchisee = await self._franchisees.get_full(franchisee_id)
        if franchisee is None:
            raise EntityNotFoundError("Руководитель филиала не найден.")
        return franchisee

    async def block_franchisee(self, franchisee_id: UUID, *, blocked: bool) -> Franchisee:
        franchisee = await self.get_franchisee(franchisee_id)
        return await self._franchisees.set_blocked(franchisee, blocked, reason="Заблокирован основным руководителем")

    async def delete_franchisee(self, franchisee_id: UUID) -> Franchisee:
        franchisee = await self.get_franchisee(franchisee_id)
        if franchisee.telegram_user:
            franchisee.telegram_user.is_active = False
        await self._session.delete(franchisee)
        await self._session.flush()
        return franchisee

    async def toggle_franchisee_global_permission(self, franchisee_id: UUID, field_name: str) -> Franchisee:
        franchisee = await self.get_franchisee(franchisee_id)
        if field_name not in {
            "can_view_owner_branches",
            "can_message_owner_employees",
            "can_receive_owner_statistics",
        }:
            raise ValidationError("Неизвестная настройка доступа.")
        setattr(franchisee, field_name, not getattr(franchisee, field_name))
        await self._session.flush()
        return await self._franchisees.get_by_telegram_user_id(franchisee.telegram_user_id) or franchisee

    async def toggle_franchisee_branch_access(self, franchisee_id: UUID, branch_id: UUID, field_name: str) -> Franchisee:
        franchisee = await self.get_franchisee(franchisee_id)
        branch = await self.get_branch(branch_id)
        existing = await self._franchise_accesses.get_for_pair(franchisee.id, branch.id)
        can_view = existing.can_view_statistics if existing else False
        can_message = existing.can_message_employees if existing else False
        can_manage = existing.can_manage_employees if existing else False
        if field_name == "view":
            can_view = not can_view
        elif field_name == "message":
            can_message = not can_message
        elif field_name == "manage":
            can_manage = not can_manage
        else:
            raise ValidationError("Неизвестная настройка филиала.")
        await self._franchise_accesses.upsert(
            franchisee_id=franchisee.id,
            branch_id=branch.id,
            can_view_statistics=can_view,
            can_message_employees=can_message,
            can_manage_employees=can_manage,
        )
        return await self._franchisees.get_by_telegram_user_id(franchisee.telegram_user_id) or franchisee

    async def sync_branch(self, branch_id: UUID) -> Branch:
        branch = await self.get_branch(branch_id)
        await self._sync.sync_branch(branch)
        return branch

    async def check_branch_connection(self, branch_id: UUID) -> Branch:
        return await self.sync_branch(branch_id)

    async def sync_all(self) -> list[Branch]:
        company = await self._require_company()
        return await self._sync.sync_company(company)

    async def setup_yclients(
        self,
        *,
        api_key: str,
        partner_id: int,
        user_token: str | None = None,
    ) -> Company:
        current_company = await self._companies.get_default()
        if current_company is not None:
            await self._branches.delete_legacy_seed_branch(
                current_company.id,
                self._settings.yclients_default_company_id,
            )
        admin_password_hash = (
            current_company.admin_password_hash
            if current_company is not None
            else self._passwords.hash_password(self._settings.admin_password)
        )
        company = await self._companies.save_yclients_partner_setup(
            title=f"YCLIENTS партнёр {partner_id}",
            partner_id=partner_id,
            encrypted_api_key=self._encryption.encrypt(api_key) or "",
            encrypted_user_token=self._encryption.encrypt(user_token) if user_token else None,
            admin_password_hash=admin_password_hash,
            timezone=self._settings.timezone,
            synchronization_interval_minutes=self._settings.sync_interval_minutes,
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
        return company

    async def setup_yclients_user_token(self, user_token: str | None, *, validate_manual: bool = True) -> Company:
        company = await self._require_company()
        cleaned_user_token = user_token.strip() if user_token else None
        if cleaned_user_token and validate_manual and len(cleaned_user_token) < 20:
            raise ValidationError("User token выглядит слишком коротким. Вставьте полный токен из YCLIENTS.")
        encrypted_user_token = self._encryption.encrypt(cleaned_user_token) if cleaned_user_token else None
        await self._companies.update_yclients_user_token(company, encrypted_user_token)
        return company

    async def setup_yclients_login_password(
        self,
        *,
        login: str,
        password: str,
        telegram_id: int | None = None,
    ) -> Company:
        company = await self._require_company()
        if not self._company_has_yclients_credentials(company):
            raise EntityNotFoundError("Сначала укажите YCLIENTS API key и Partner ID.")
        if not login.strip():
            raise ValidationError("Введите телефон или email от аккаунта YCLIENTS.")
        if not password:
            raise ValidationError("Введите пароль от аккаунта YCLIENTS.")
        user_token = await self._client_for_company(company).authenticate_user(login, password)
        if telegram_id is not None:
            user = await self.ensure_manager(telegram_id)
            if user.role == Role.FRANCHISEE:
                franchisee = await self._require_franchisee(user)
                await self._franchisees.update_yclients_user_token(
                    franchisee,
                    self._encryption.encrypt(user_token),
                )
                return company
        return await self.setup_yclients_user_token(user_token, validate_manual=False)

    async def regulation_text(self, *, for_admin: bool = False) -> str:
        company = await self._require_company()
        regulation = (company.regulation_text or "").strip()
        file_name = (company.regulation_file_name or "").strip()
        if company.regulation_file_id:
            parts = [
                bold("РЕГЛАМЕНТ"),
                pre([f"Файл {file_name or 'документ'}"]),
            ]
            if regulation:
                parts.append(regulation)
            if for_admin:
                parts.append(blockquote("Барберы получают этот файл в своём меню и не могут его редактировать."))
            return "\n\n".join(parts)
        if not regulation:
            message = (
                "Регламент пока не добавлен. Нажмите «Изменить регламент» и отправьте текст или PDF/DOCX одним сообщением."
                if for_admin
                else "Регламент пока не добавлен. Руководитель добавит его в панели управления."
            )
            return "\n\n".join([bold("РЕГЛАМЕНТ"), blockquote(message)])
        parts = [bold("РЕГЛАМЕНТ"), regulation]
        if for_admin:
            parts.append(blockquote("Барберы видят этот текст в своём меню и не могут его редактировать."))
        return "\n\n".join(parts)

    async def update_regulation_text(self, text: str | None) -> Company:
        company = await self._require_company()
        cleaned_text = (text or "").strip() or None
        return await self._companies.update_regulation_text(company, cleaned_text)

    async def update_regulation_file(self, *, file_id: str, file_name: str | None, caption: str | None) -> Company:
        company = await self._require_company()
        cleaned_caption = (caption or "").strip() or None
        return await self._companies.update_regulation_file(
            company,
            file_id=file_id,
            file_name=file_name,
            caption=cleaned_caption,
        )

    async def regulation_document(self) -> tuple[str | None, str | None, str | None]:
        company = await self._require_company()
        return company.regulation_file_id, company.regulation_file_name, company.regulation_text

    async def kpi_settings_text(self) -> str:
        company = await self._require_company()
        rules = await self._kpi_rules.list_active(company.id)
        lines = [
            f"{money(rule.threshold_amount):>12}  {rule.percent.quantize(Decimal('0.01'))}%"
            for rule in rules
        ]
        if not lines:
            lines = ["Правила KPI пока не настроены."]
        return "\n\n".join(
            [
                bold("НАСТРОЙКА KPI"),
                pre(["Порог KPI       Процент", *lines]),
                blockquote(
                    [
                        "KPI база считается как дополнительные услуги + товары.",
                        "Порог 37 000 ₽ даёт +2%, порог 60 000 ₽ даёт +5% к проценту от услуг.",
                        "Процент применяется со следующего месяца после закрытия текущего.",
                    ]
                ),
            ]
        )

    async def update_kpi_rules_from_text(self, text: str) -> None:
        company = await self._require_company()
        parsed_rules = _parse_kpi_rules(text)
        await self._kpi_rules.replace_rules(company.id, parsed_rules)

    async def grade_settings_text(self) -> str:
        company = await self._require_company()
        rules = await self._grade_rules.ensure_defaults(company.id)
        lines = [
            (
                f"{rule.sort_order:>2}. {rule.category_title:<18} "
                f"{money(rule.base_price):>8}  "
                f"{money(rule.average_daily_revenue_required):>10}/дн  "
                f"{rule.months_required:>2} мес  "
                f"стаж {rule.minimum_employment_months:>2} мес"
            )
            for rule in rules
        ]
        return "\n\n".join(
            [
                bold("НАСТРОЙКА GRADE UP"),
                pre(["Уровень              Стрижка   Средн./день   Период   Стаж", *lines]),
                blockquote(
                    [
                        "Переход считается по средней дневной выручке услуг за период.",
                        "Товары в Grade Up не входят.",
                        "Формат изменения: название = цена, среднедневная выручка, месяцев периода, минимальный стаж.",
                    ]
                ),
            ]
        )

    async def update_grade_rules_from_text(self, text: str) -> None:
        company = await self._require_company()
        parsed_rules = _parse_grade_rules(text)
        await self._grade_rules.replace_rules(company.id, parsed_rules)

    async def reset_to_registration(self) -> None:
        company = await self._require_company()
        admin_password_hash = company.admin_password_hash
        for branch in await self._branches.list_by_company(company.id):
            await self._branches.delete_branch(branch)
        deleted_users = await self._telegram_users.delete_all_users()
        company.title = "Компания не настроена"
        company.partner_id = 0
        company.default_company_id = 0
        company.encrypted_yclients_api_key = self._encryption.encrypt("") or ""
        company.encrypted_yclients_user_token = None
        company.admin_password_hash = admin_password_hash
        company.regulation_text = None
        company.synchronization_interval_minutes = self._settings.sync_interval_minutes
        await self._kpi_rules.replace_rules(company.id, _default_kpi_rules())
        await self._grade_rules.ensure_defaults(company.id)
        await self._session.flush()
        logger.info("admin_reset_to_registration", company_id=str(company.id), deleted_users=deleted_users)

    async def check_connection_text(self, telegram_id: int | None = None) -> str:
        company = await self._require_company()
        if not self._company_has_yclients_credentials(company):
            return "YCLIENTS не настроен. Укажите API key и Partner ID в настройках."
        try:
            actor = await self.ensure_manager(telegram_id) if telegram_id is not None else None
            client = await self._client_for_actor(company, actor)
            branches = await client.list_branches(company.partner_id)
        except Exception as exc:
            return "\n\n".join(
                [
                    bold("ПРОВЕРКА YCLIENTS"),
                    pre(
                        [
                            "Статус     ❌ ошибка",
                            f"Partner ID {company.partner_id}",
                            f"Ошибка     {str(exc)[:500]}",
                        ]
                    ),
                    blockquote("Проверьте API key и Partner ID в настройках."),
                ]
            )
        stored_branches = await self._branches.list_by_company(company.id)
        probe_branches = branches or [
            YClientsBranch(
                id=branch.yclients_branch_id,
                title=branch.name,
                address=branch.address,
            )
            for branch in stored_branches
        ]
        preview = [f"{branch.title} · {branch.id}" for branch in branches[:10]]
        stored_preview = [f"{branch.name} · {branch.yclients_branch_id}" for branch in stored_branches[:10]]
        capability_lines = await self._capability_lines(client, probe_branches)
        parts = [
            bold("ПРОВЕРКА YCLIENTS"),
            pre(
                [
                    "Статус     ✅ подключение работает",
                    f"Partner ID {company.partner_id}",
                    f"Филиалов через партнёра {len(branches)}",
                    f"Филиалов в боте         {len(stored_branches)}",
                ]
            ),
        ]
        if preview:
            parts.append(pre(["Доступные филиалы", *preview]))
        elif stored_preview:
            parts.append(pre(["Сохранённые филиалы", *stored_preview]))
        if capability_lines:
            parts.append(pre(["Доступ ключа", *capability_lines]))
        if not branches and stored_branches:
            parts.append(
                blockquote(
                    "YCLIENTS не вернул список филиалов по Partner ID. "
                    "Сохранённые филиалы всё равно проверяются напрямую по ID."
                )
            )
        else:
            parts.append(blockquote("Нажмите на филиал ниже, чтобы добавить его в бота и подтянуть данные."))
        return "\n\n".join(parts)

    async def available_branches(self, telegram_id: int | None = None) -> tuple[list[YClientsBranch], set[int]]:
        company = await self._require_company()
        if not self._company_has_yclients_credentials(company):
            raise EntityNotFoundError("Сначала укажите YCLIENTS API key и Partner ID.")
        actor = await self.ensure_manager(telegram_id) if telegram_id is not None else None
        client = await self._client_for_actor(company, actor)
        available = await client.list_branches(company.partner_id)
        existing = await self._branches.list_by_company(company.id)
        return available, {branch.yclients_branch_id for branch in existing}

    async def branch_details_text(self, branch: Branch) -> str:
        employees = await self._employees.list_by_branch(branch.id)
        services = await self._services.list_by_branch(branch.id)
        return "\n\n".join(
            [
                bold(branch.name.upper()),
                pre(
                    [
                        f"ID филиала       {branch.yclients_branch_id}",
                        f"Адрес            {branch.address or 'не указан'}",
                        f"Статус проверки  {branch.sync_status.value}",
                        f"Сотрудников      {len(employees)}",
                        f"Услуг            {len(services)}",
                        "Товары           напрямую из API",
                        f"Последняя проверка {branch.last_synced_at or 'ещё не было'}",
                    ]
                ),
                blockquote("Товары не синхронизируются с филиалом: они запрашиваются из YCLIENTS при открытии раздела."),
            ]
        )

    async def dashboard_text(self, telegram_id: int | None = None) -> str:
        company = await self._require_company()
        branches = await (
            self.list_visible_branches(telegram_id)
            if telegram_id is not None and await self.is_manager(telegram_id)
            else self._branches.list_by_company(company.id)
        )
        employees_count = sum(branch.employees_count for branch in branches)
        yclients_status = "✅ настроен" if self._company_has_yclients_credentials(company) else "❌ не настроен"
        user_token_status = self._company_user_token_status(company)
        role_line = None
        if telegram_id is not None:
            user = await self._telegram_users.get_by_telegram_id(telegram_id)
            if user and user.role == Role.FRANCHISEE:
                role_line = "Роль           руководитель филиала"
                franchisee = await self._franchisees.get_by_telegram_user_id(user.id)
                if franchisee is not None:
                    user_token_status = self._token_status(
                        self._encryption.decrypt(franchisee.encrypted_yclients_user_token)
                    )
        return "\n\n".join(
            [
                bold("ПАНЕЛЬ РУКОВОДИТЕЛЯ"),
                pre(
                    [
                        *([role_line] if role_line else []),
                        f"Компания       {company.title}",
                        f"YCLIENTS       {yclients_status}",
                        f"User token     {user_token_status}",
                        f"Филиалов       {len(branches)}",
                        f"Сотрудников    {employees_count}",
                        f"Проверка       каждые {company.synchronization_interval_minutes} мин.",
                    ]
                ),
            ]
        )

    async def _require_company(self) -> Company:
        company = await self._companies.get_default()
        if company is None:
            raise EntityNotFoundError("Компания ещё не настроена.")
        return company

    async def _require_franchisee(self, user: TelegramUser) -> Franchisee:
        franchisee = await self._franchisees.get_by_telegram_user_id(user.id)
        if franchisee is None or franchisee.is_blocked:
            raise AccessDeniedError("Доступ руководителя филиала заблокирован.")
        return franchisee

    async def franchisee_has_yclients_user_token(self, telegram_id: int) -> bool:
        user = await self.ensure_manager(telegram_id)
        if user.role != Role.FRANCHISEE:
            return True
        franchisee = await self._require_franchisee(user)
        token = self._encryption.decrypt(franchisee.encrypted_yclients_user_token)
        return bool(token and len(token.strip()) >= 20)

    def _client_for_company(self, company: Company) -> YClientsClient:
        partner_token = self._encryption.decrypt(company.encrypted_yclients_api_key)
        return self._client(company, user_token=self._company_user_token(company), partner_token=partner_token)

    async def _client_for_actor(self, company: Company, user: TelegramUser | None) -> YClientsClient:
        partner_token = self._encryption.decrypt(company.encrypted_yclients_api_key)
        user_token = self._company_user_token(company)
        if user is not None and user.role == Role.FRANCHISEE:
            franchisee = await self._require_franchisee(user)
            token = self._encryption.decrypt(franchisee.encrypted_yclients_user_token)
            if token:
                user_token = token
            else:
                raise ValidationError("Сначала войдите в YCLIENTS, чтобы бот получил доступ к вашим филиалам.")
        return self._client(company, user_token=user_token, partner_token=partner_token)

    def _client(self, company: Company, *, user_token: str | None, partner_token: str | None) -> YClientsClient:
        return YClientsClient(
            base_url=self._settings.yclients_base_url_str,
            partner_token=partner_token or self._settings.yclients_partner_token,
            user_token=user_token,
            timeout_seconds=self._settings.yclients_timeout_seconds,
            product_max_pages=self._settings.yclients_product_max_pages,
        )

    def _company_user_token(self, company: Company) -> str | None:
        return self._encryption.decrypt(company.encrypted_yclients_user_token) or self._settings.yclients_user_token

    def _company_user_token_status(self, company: Company) -> str:
        return self._token_status(self._company_user_token(company))

    def _token_status(self, user_token: str | None) -> str:
        if not user_token:
            return "❌ не настроен"
        if len(user_token.strip()) < 20:
            return "❌ слишком короткий"
        return "✅ настроен"

    def _company_has_yclients_credentials(self, company: Company) -> bool:
        partner_token = self._encryption.decrypt(company.encrypted_yclients_api_key)
        return bool(
            partner_token
            and company.partner_id > 0
            and company.default_company_id == 0
            and company.title not in {self._settings.default_company_title, "Компания не настроена"}
        )

    async def _capability_lines(self, client: YClientsClient, branches: list[YClientsBranch]) -> list[str]:
        if not branches:
            return []
        company_id = branches[0].id
        lines = ["Филиалы        ✅"]
        employees = []
        try:
            employees = await client.list_employees(company_id)
            lines.append(f"Сотрудники     ✅ {len(employees)}")
        except Exception as exc:
            lines.append(f"Сотрудники     ❌ {str(exc)[:80]}")
        try:
            services = await client.list_services(company_id)
            lines.append(f"Услуги         ✅ {len(services)}")
        except Exception as exc:
            lines.append(f"Услуги         ❌ {str(exc)[:80]}")
        try:
            products = await client.list_products(company_id)
            lines.append(f"Товары         ✅ {len(products)}")
        except Exception as exc:
            lines.append(f"Товары         ❌ {_yclients_capability_error(exc)}")
        if employees:
            try:
                await client.get_daily_statistics(
                    company_id=company_id,
                    employee_staff_id=employees[0].id,
                    statistic_date=date.today(),
                )
                lines.append("Записи/стат.   ✅")
            except Exception as exc:
                lines.append(f"Записи/стат.   ❌ {_yclients_capability_error(exc)}")
        else:
            lines.append("Записи/стат.   ❌ нет сотрудника для проверки")
        return lines


def _parse_kpi_rules(text: str) -> list[tuple[Decimal, Decimal]]:
    rules: list[tuple[Decimal, Decimal]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        compact_line = line.replace(" ", "").replace("\u00a0", "")
        numbers = re.findall(r"\d+(?:[,.]\d+)?", compact_line)
        if len(numbers) < 2:
            raise ValidationError("Каждая строка KPI должна содержать порог и процент.")
        threshold = Decimal(numbers[0].replace(",", "."))
        percent = Decimal(numbers[1].replace(",", "."))
        if threshold < 0:
            raise ValidationError("Порог KPI не может быть отрицательным.")
        if percent < 0 or percent > 100:
            raise ValidationError("Процент KPI должен быть от 0 до 100.")
        rules.append((threshold, percent))
    if not rules:
        raise ValidationError("Добавьте хотя бы одно правило KPI.")
    if not any(threshold == 0 for threshold, _ in rules):
        rules.append((Decimal("0"), Decimal("0")))
    unique_rules = {threshold: percent for threshold, percent in rules}
    return sorted(unique_rules.items(), key=lambda item: item[0])


def _parse_grade_rules(text: str) -> list[tuple[str, Decimal, Decimal, int, int]]:
    rules: list[tuple[str, Decimal, Decimal, int, int]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        numbers = re.findall(r"\d+(?:[,.]\d+)?", line.replace("\u00a0", " "))
        if len(numbers) < 4:
            raise ValidationError(
                "Каждая строка Grade Up должна содержать цену стрижки, среднюю выручку/день, период в месяцах и стаж."
            )
        first_number_index = line.find(numbers[0])
        title_part = line[:first_number_index].replace("=", "").replace("-", "").strip(" :;")
        base_price = Decimal(numbers[0].replace(",", "."))
        average_daily_revenue = Decimal(numbers[1].replace(",", "."))
        months_required = int(Decimal(numbers[2].replace(",", ".")))
        min_months = int(Decimal(numbers[3].replace(",", ".")))
        if base_price <= 0 or average_daily_revenue <= 0:
            raise ValidationError("Цена и средняя выручка Grade Up должны быть больше нуля.")
        if months_required <= 0 or min_months < 0:
            raise ValidationError("Период должен быть больше нуля, стаж не может быть отрицательным.")
        title = title_part or _default_grade_title(base_price)
        rules.append((title, base_price, average_daily_revenue, months_required, min_months))
    if not rules:
        raise ValidationError("Добавьте хотя бы одно правило Grade Up.")
    return rules


def _default_grade_title(base_price: Decimal) -> str:
    return {
        Decimal("1500"): "Мастер",
        Decimal("1700"): "Старший мастер",
        Decimal("1900"): "Эксперт",
        Decimal("2300"): "Старший эксперт",
    }.get(base_price, f"{money(base_price)}")


def _generate_plain_code(length: int = 8) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _profile_title(profile: TelegramProfile) -> str:
    name = " ".join(part for part in (profile.first_name, profile.last_name) if part).strip()
    if name:
        return name
    if profile.username:
        return f"@{profile.username}"
    return f"Telegram {profile.id}"


def _default_kpi_rules() -> list[tuple[Decimal, Decimal]]:
    return [
        (Decimal("0"), Decimal("0")),
        (Decimal("37000"), Decimal("2")),
        (Decimal("60000"), Decimal("5")),
    ]


def _yclients_capability_error(exc: Exception) -> str:
    message = str(exc)
    lowered = message.casefold()
    if "нет прав на управление филиалом" in lowered:
        return "токен принят, но нет прав на этот филиал"
    if "недостаточно прав" in lowered or "403" in lowered:
        return "токен принят, но недостаточно прав"
    if "401" in lowered or "идентификатор пользователя" in lowered or "user token" in lowered:
        return "YCLIENTS не увидел User token"
    return message[:90]
