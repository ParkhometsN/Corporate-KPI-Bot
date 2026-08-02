from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards.admin import admin_main_keyboard
from app.bot.keyboards.employee import employee_main_keyboard
from app.bot.keyboards.common import remove_keyboard
from app.bot.states.employee import EmployeeConnectionStates
from app.services.factory import ServiceContainer

router = Router(name="common")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    await state.clear()
    if await services.admin.is_manager(message.from_user.id):
        await message.answer(
            await services.admin.dashboard_text(),
            reply_markup=admin_main_keyboard(),
        )
        return
    employee = await services.connection.get_employee_by_telegram_id(message.from_user.id)
    if employee:
        await message.answer(
            f"Здравствуйте, {employee.full_name}.\nВыберите раздел:",
            reply_markup=employee_main_keyboard(),
        )
        return
    payload = _start_payload(message.text)
    if payload:
        if payload.startswith("fr_"):
            franchisee = await services.admin.bind_franchisee(message.from_user, payload)
            await message.answer(
                f"Готово, вы подключены как руководитель филиала: {franchisee.title}.",
                reply_markup=admin_main_keyboard(),
            )
            return
        employee = await services.connection.bind_employee(message.from_user, payload)
        await message.answer(
            f"Готово, Telegram подключён к сотруднику {employee.full_name}.",
            reply_markup=employee_main_keyboard(),
        )
        return
    await state.set_state(EmployeeConnectionStates.waiting_code)
    await message.answer(
        "Здравствуйте.\nВведите код подключения, который выдал руководитель.",
        reply_markup=remove_keyboard(),
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=remove_keyboard())


@router.message(EmployeeConnectionStates.waiting_code, F.text)
async def bind_employee(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    employee = await services.connection.bind_employee(message.from_user, message.text)
    await state.clear()
    await message.answer(
        f"Готово, Telegram подключён к сотруднику {employee.full_name}.",
        reply_markup=employee_main_keyboard(),
    )


def _start_payload(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    return parts[1].strip() or None
