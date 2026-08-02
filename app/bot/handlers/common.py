from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from app.bot.keyboards.admin import (
    admin_main_keyboard,
    back_to_employees_keyboard,
    back_to_franchisees_keyboard,
    franchisee_main_keyboard,
    yclients_login_cancel_keyboard,
)
from app.bot.keyboards.employee import employee_main_keyboard
from app.bot.keyboards.common import remove_keyboard
from app.bot.states.admin import AdminYClientsLoginStates
from app.bot.states.employee import EmployeeConnectionStates
from app.config.logging import get_logger
from app.services.factory import ServiceContainer
from app.utils.telegram_formatting import blockquote, bold

router = Router(name="common")
logger = get_logger(__name__)


def _text_is_not_command(message: Message) -> bool:
    return not (message.text or "").lstrip().startswith("/")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    await state.clear()
    payload = _start_payload(message.text)
    logger.info(
        "start_command_received",
        telegram_id=message.from_user.id,
        has_payload=bool(payload),
        payload_kind=_payload_kind(payload),
        payload_length=len(payload or ""),
    )
    if payload and payload.startswith("fr_"):
        await _bind_franchisee_by_code(message, state, services, payload)
        return
    if await services.admin.is_manager(message.from_user.id):
        await message.answer(
            await services.admin.dashboard_text(message.from_user.id),
            reply_markup=admin_main_keyboard()
            if await services.admin.is_admin(message.from_user.id)
            else franchisee_main_keyboard(),
        )
        return
    if payload:
        employee = await services.connection.bind_employee(message.from_user, payload)
        await _notify_admin_connection_success(message, services, payload, employee)
        await message.answer(
            f"Готово, Telegram подключён к сотруднику {employee.full_name}.",
            reply_markup=employee_main_keyboard(),
        )
        return
    employee = await services.connection.get_employee_by_telegram_id(message.from_user.id)
    if employee:
        await message.answer(
            f"Здравствуйте, {employee.full_name}.\nВыберите раздел:",
            reply_markup=employee_main_keyboard(),
        )
        return
    await state.set_state(EmployeeConnectionStates.waiting_code)
    await message.answer(
        "Здравствуйте.\nВведите код подключения сотрудника или руководителя филиала.",
        reply_markup=remove_keyboard(),
    )


@router.message(F.text.regexp(r"^fr_[A-Za-z0-9_-]+$"))
async def bind_franchisee_code(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    await _bind_franchisee_by_code(message, state, services, (message.text or "").strip())


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=remove_keyboard())


@router.message(EmployeeConnectionStates.waiting_code, F.text, _text_is_not_command)
async def bind_employee(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    code = (message.text or "").strip()
    if code.startswith("fr_"):
        await _bind_franchisee_by_code(message, state, services, code)
        return
    employee = await services.connection.bind_employee(message.from_user, code)
    await _notify_admin_connection_success(message, services, code, employee)
    await state.clear()
    await message.answer(
        f"Готово, Telegram подключён к сотруднику {employee.full_name}.",
        reply_markup=employee_main_keyboard(),
    )


async def _bind_franchisee_by_code(
    message: Message,
    state: FSMContext,
    services: ServiceContainer,
    code: str,
) -> None:
    if await services.admin.is_admin(message.from_user.id):
        await state.clear()
        await message.answer(
            "\n\n".join(
                [
                    bold("ССЫЛКА ДЛЯ РУКОВОДИТЕЛЯ ФИЛИАЛА"),
                    blockquote(
                        [
                            "Эта ссылка предназначена для другого Telegram-аккаунта.",
                            "Отправьте её будущему руководителю филиала. Ваш аккаунт уже является главным руководителем.",
                        ]
                    ),
                ]
            ),
            reply_markup=admin_main_keyboard(),
        )
        return
    logger.info(
        "franchise_invite_binding_started",
        telegram_id=message.from_user.id,
        code_length=len(code),
    )
    franchisee = await services.admin.bind_franchisee(message.from_user, code)
    await _notify_franchise_connection_success(message, services, code, franchisee)
    await state.set_state(AdminYClientsLoginStates.waiting_login)
    await message.answer(
        "\n\n".join(
            [
                bold("РУКОВОДИТЕЛЬ ФИЛИАЛА ПОДКЛЮЧЁН"),
                blockquote(
                    [
                        f"Профиль: {franchisee.title}",
                        "Теперь войдите в YCLIENTS, чтобы бот мог видеть ваши филиалы, сотрудников и статистику.",
                    ]
                ),
                _yclients_login_prompt_text(),
            ]
        ),
        reply_markup=yclients_login_cancel_keyboard(),
    )


async def _notify_admin_connection_success(
    message: Message,
    services: ServiceContainer,
    code: str,
    employee,
) -> None:
    admin_message = await services.connection.admin_message_for_code(code)
    if admin_message is None:
        return
    try:
        await message.bot.edit_message_text(
            "\n".join(
                [
                    "СОТРУДНИК ПОДКЛЮЧЁН",
                    "",
                    f"Сотрудник: {employee.full_name}",
                    "Статус: Telegram успешно подключён.",
                ]
            ),
            chat_id=admin_message.chat_id,
            message_id=admin_message.message_id,
            reply_markup=back_to_employees_keyboard(employee.branch_id),
        )
    except TelegramBadRequest:
        return


async def _notify_franchise_connection_success(
    message: Message,
    services: ServiceContainer,
    code: str,
    franchisee,
) -> None:
    admin_message = await services.admin.franchise_invite_admin_message(code)
    if admin_message is None:
        return
    try:
        await message.bot.edit_message_text(
            "\n".join(
                [
                    "РУКОВОДИТЕЛЬ ФИЛИАЛА ПОДКЛЮЧЁН",
                    "",
                    f"Профиль: {franchisee.title}",
                    "Статус: Telegram успешно подключён.",
                ]
            ),
            chat_id=admin_message.chat_id,
            message_id=admin_message.message_id,
            reply_markup=back_to_franchisees_keyboard(),
        )
    except TelegramBadRequest:
        return


def _yclients_login_prompt_text() -> str:
    return "\n\n".join(
        [
            bold("ВХОД В YCLIENTS"),
            blockquote(
                [
                    "Введите телефон или email от аккаунта YCLIENTS.",
                    "Следующим сообщением бот попросит пароль и сохранит только User token.",
                ]
            ),
        ]
    )


def _start_payload(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    return parts[1].strip() or None


def _payload_kind(payload: str | None) -> str:
    if not payload:
        return "none"
    if payload.startswith("fr_"):
        return "franchise"
    return "employee"
