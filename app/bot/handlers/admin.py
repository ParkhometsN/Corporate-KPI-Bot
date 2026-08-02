from contextlib import suppress
from uuid import UUID

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.loading import RichMessageResult, answer_with_loading, edit_with_loading
from app.bot.keyboards.admin import (
    admin_kpi_edit_keyboard,
    admin_kpi_keyboard,
    admin_grade_edit_keyboard,
    admin_grade_keyboard,
    admin_main_keyboard,
    admin_regulation_edit_keyboard,
    admin_regulation_keyboard,
    admin_reset_confirm_keyboard,
    admin_settings_keyboard,
    available_branches_keyboard,
    back_to_employees_keyboard,
    branch_delete_confirm_keyboard,
    branch_dashboard_keyboard,
    branch_stats_period_keyboard,
    broadcast_action_keyboard,
    broadcast_branch_keyboard,
    broadcast_cancel_keyboard,
    broadcast_confirm_keyboard,
    branches_keyboard,
    employee_admin_keyboard,
    employees_keyboard,
    franchise_delete_confirm_keyboard,
    franchisee_keyboard,
    franchisees_keyboard,
    team_stats_period_keyboard,
    yclients_login_cancel_keyboard,
)
from app.bot.states.admin import (
    AdminAuthStates,
    AdminBranchStates,
    AdminBroadcastStates,
    AdminCompanySetupStates,
    AdminGradeStates,
    AdminKpiStates,
    AdminRegulationStates,
    AdminYClientsLoginStates,
)
from app.services.factory import ServiceContainer
from app.services.statistics import _period_lines
from app.utils.exceptions import AppError
from app.utils.rich_messages import rich_message, table, table_rows
from app.utils.telegram_formatting import blockquote, bold, html_escape, pre, shorten

router = Router(name="admin")

_FRANCHISE_GLOBAL_FIELDS = {
    "v": "can_view_owner_branches",
    "m": "can_message_owner_employees",
    "s": "can_receive_owner_statistics",
}
_FRANCHISE_BRANCH_FIELDS = {
    "v": "view",
    "m": "message",
    "g": "manage",
}


@router.message(Command("admin"))
async def admin_start(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    if await services.admin.is_manager(message.from_user.id):
        if not await services.admin.is_yclients_configured():
            await state.set_state(AdminCompanySetupStates.waiting_api_key)
            await message.answer("YCLIENTS ещё не подключён.\nВведите API key.")
            return
        await state.clear()
        await message.answer(
            await services.admin.dashboard_text(message.from_user.id),
            reply_markup=admin_main_keyboard(),
        )
        return
    if not await services.admin.has_registered_admins():
        await state.set_state(AdminAuthStates.waiting_initial_password)
        await message.answer(
            "Первый запуск панели руководителя.\n\n"
            "Вы будете зарегистрированы как первый руководитель. "
            "Придумайте пароль для дальнейших входов."
        )
        return
    await state.set_state(AdminAuthStates.waiting_password)
    await message.answer("Введите пароль руководителя.")


@router.message(AdminAuthStates.waiting_initial_password, F.text)
async def admin_initial_password(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    await services.admin.register_initial_admin(message.from_user, message.text)
    await _try_delete(message)
    await state.set_state(AdminCompanySetupStates.waiting_api_key)
    await message.answer(
        "Готово. Вы зарегистрированы как руководитель.\n\n"
        "Теперь подключим YCLIENTS.\nВведите API key."
    )


@router.message(AdminAuthStates.waiting_password, F.text)
async def admin_password(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    await services.admin.authenticate(message.from_user, message.text)
    await _try_delete(message)
    await state.clear()
    await message.answer(
        await services.admin.dashboard_text(),
        reply_markup=admin_main_keyboard(),
    )


@router.callback_query(F.data == "admin:dashboard")
async def admin_dashboard(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_manager(callback, services)
    await state.clear()
    await _safe_edit_text(
        callback.message,
        await services.admin.dashboard_text(callback.from_user.id),
        reply_markup=None,
    )
    await callback.answer()


@router.message(StateFilter(None), F.text.in_({"Панель руководителя", "Главная"}))
async def admin_dashboard_button(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    await services.admin.ensure_manager(message.from_user.id)
    await state.clear()
    await message.answer(await services.admin.dashboard_text(message.from_user.id), reply_markup=admin_main_keyboard())


@router.message(StateFilter(None), F.text.in_({"Филиалы", "🏢 Филиалы"}))
async def admin_branches_button(message: Message, services: ServiceContainer) -> None:
    await services.admin.ensure_manager(message.from_user.id)
    branches = await services.admin.list_visible_branches(message.from_user.id)
    await message.answer(_branches_text(branches), reply_markup=branches_keyboard(branches))


@router.message(StateFilter(None), F.text.in_({"Статистика команды", "📊 Статистика команды"}))
async def admin_team_stats_button(message: Message, services: ServiceContainer) -> None:
    await services.admin.ensure_manager(message.from_user.id)

    async def load_team_stats():
        employees = await services.admin.get_visible_team_employees(message.from_user.id)
        try:
            await services.statistics.refresh_team_period(employees, "month")
        except Exception:
            pass
        return RichMessageResult(
            rich_message=await services.statistics.team_stats_rich_message(employees, "month", title="вся команда"),
            fallback_text=await services.statistics.team_stats_text(employees, "month", title="вся команда", refresh=False),
            reply_markup=team_stats_period_keyboard("month"),
        )

    await answer_with_loading(
        message,
        title="ЗАГРУЗКА СТАТИСТИКИ",
        detail="Собираю данные по всем сотрудникам.",
        producer=load_team_stats,
    )


@router.message(StateFilter(None), F.text.in_({"Действия для барберов", "📣 Действия для барберов"}))
async def admin_broadcast_button(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    await services.admin.ensure_manager(message.from_user.id)
    await state.clear()
    branches = await services.admin.list_visible_branches(message.from_user.id)
    if not branches:
        await message.answer(
            "\n\n".join(
                [
                    bold("ДЕЙСТВИЯ ДЛЯ БАРБЕРОВ"),
                    blockquote("Сначала добавьте филиал и синхронизируйте сотрудников."),
                ]
            ),
            reply_markup=admin_main_keyboard(),
        )
        return
    if len(branches) == 1:
        await _show_broadcast_actions(message, state, services, branches[0].id, actor_id=message.from_user.id, edit=False)
        return
    await state.set_state(AdminBroadcastStates.choosing_branch)
    await message.answer(
        "\n\n".join(
            [
                bold("ДЕЙСТВИЯ ДЛЯ БАРБЕРОВ"),
                blockquote("Выберите филиал или отправьте действие всем подключённым сотрудникам."),
            ]
        ),
        reply_markup=broadcast_branch_keyboard(branches),
    )


@router.message(StateFilter(None), F.text == "Регламент компании")
async def admin_regulation_button(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    await services.admin.ensure_admin(message.from_user.id)
    await state.clear()
    await message.answer(
        await services.admin.regulation_text(for_admin=True),
        reply_markup=admin_regulation_keyboard(),
    )


@router.message(StateFilter(None), F.text == "KPI команды")
async def admin_kpi_button(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    await services.admin.ensure_admin(message.from_user.id)
    await state.clear()
    await message.answer(await services.admin.kpi_settings_text(), reply_markup=admin_main_keyboard())


@router.message(StateFilter(None), F.text == "Настройки руководителя")
async def admin_settings_button(message: Message, services: ServiceContainer) -> None:
    await services.admin.ensure_admin(message.from_user.id)
    await message.answer(bold("НАСТРОЙКИ"), reply_markup=admin_settings_keyboard())


@router.message(StateFilter(None), F.text.in_({"Франчайзи", "Руководители филиалов"}))
async def admin_franchisees_button(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    await services.admin.ensure_admin(message.from_user.id)
    await state.clear()
    franchisees = await services.admin.list_franchisees()
    await message.answer(
        _franchisees_text(franchisees),
        reply_markup=franchisees_keyboard(franchisees),
    )


@router.message(StateFilter(None), F.text.in_({"Проверка подключения", "✅ Проверка подключения"}))
async def admin_check_connection_button(message: Message, services: ServiceContainer) -> None:
    await services.admin.ensure_admin(message.from_user.id)

    async def check_connection():
        text = await services.admin.check_connection_text()
        try:
            available, existing_ids = await services.admin.available_branches()
            keyboard = available_branches_keyboard(available, existing_ids)
        except Exception:
            keyboard = None
        return text, keyboard

    await answer_with_loading(
        message,
        title="ПРОВЕРКА YCLIENTS",
        detail="Запрашиваю доступные филиалы.",
        producer=check_connection,
    )


@router.callback_query(F.data == "admin:branches")
async def admin_branches(callback: CallbackQuery, services: ServiceContainer) -> None:
    await _ensure_manager(callback, services)
    branches = await services.admin.list_visible_branches(callback.from_user.id)
    await _safe_edit_text(callback.message, _branches_text(branches), reply_markup=branches_keyboard(branches))
    await callback.answer()


@router.callback_query(F.data == "admin:available_branches")
async def admin_available_branches(callback: CallbackQuery, services: ServiceContainer) -> None:
    await _ensure_manager(callback, services)
    await callback.answer()

    async def load_available_branches():
        try:
            available, existing_ids = await services.admin.available_branches()
        except Exception:
            return await services.admin.check_connection_text(), None
        text = "\n\n".join(
            [
                bold("ДОСТУПНЫЕ ФИЛИАЛЫ YCLIENTS"),
                blockquote(
                    "Нажмите на филиал, чтобы добавить его в бота."
                    if available
                    else "YCLIENTS не вернул доступные филиалы. Можно ввести ID вручную."
                ),
            ]
        )
        return text, available_branches_keyboard(available, existing_ids)

    await edit_with_loading(
        callback.message,
        title="ЗАГРУЗКА ФИЛИАЛОВ",
        detail="Проверяю доступные филиалы YCLIENTS.",
        producer=load_available_branches,
    )


@router.callback_query(F.data == "admin:add_branch")
async def admin_add_branch(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_manager(callback, services)
    await state.set_state(AdminBranchStates.waiting_branch_id)
    await callback.message.answer("Введите ID филиала YCLIENTS.")
    await callback.answer()


@router.message(AdminBranchStates.waiting_branch_id, F.text)
async def admin_add_branch_id(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    try:
        branch_id = int(message.text.strip())
    except ValueError:
        await message.answer("ID филиала должен быть числом.")
        return

    async def add_branch():
        branch = await services.admin.add_branch(branch_id, created_by_telegram_id=message.from_user.id)
        await state.clear()
        return (
            f"{bold('ФИЛИАЛ ДОБАВЛЕН')}\n\n{await services.admin.branch_details_text(branch)}",
            branch_dashboard_keyboard(branch.id),
        )

    await answer_with_loading(
        message,
        title="ДОБАВЛЕНИЕ ФИЛИАЛА",
        detail="Подтягиваю сотрудников и услуги из YCLIENTS.",
        producer=add_branch,
    )


@router.callback_query(F.data.startswith("available_branch:"))
async def available_branch_callback(callback: CallbackQuery, services: ServiceContainer) -> None:
    await _ensure_manager(callback, services)
    _, action, yclients_branch_id = callback.data.split(":")
    if action == "exists":
        await callback.answer("Этот филиал уже добавлен.")
        return
    await callback.answer()

    async def add_branch():
        branch = await services.admin.add_branch(int(yclients_branch_id), created_by_telegram_id=callback.from_user.id)
        return (
            f"{bold('ФИЛИАЛ ДОБАВЛЕН')}\n\n{await services.admin.branch_details_text(branch)}",
            branch_dashboard_keyboard(branch.id),
        )

    await edit_with_loading(
        callback.message,
        title="ДОБАВЛЕНИЕ ФИЛИАЛА",
        detail="Подтягиваю сотрудников и услуги из YCLIENTS.",
        producer=add_branch,
    )


@router.callback_query(F.data == "admin:setup_yclients")
async def admin_setup_yclients(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await state.update_data(setup_mode="full")
    await state.set_state(AdminCompanySetupStates.waiting_api_key)
    await callback.message.answer("Введите YCLIENTS API key.")
    await callback.answer()


@router.callback_query(F.data == "admin:setup_user_token")
async def admin_setup_user_token(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await state.update_data(setup_mode="user_token_only")
    await state.set_state(AdminCompanySetupStates.waiting_user_token)
    await callback.message.answer(
        "\n\n".join(
            [
                bold("USER TOKEN YCLIENTS"),
                blockquote("Введите User token. Чтобы очистить сохранённый токен, отправьте -"),
            ]
        )
    )
    await callback.answer()


@router.callback_query(F.data == "admin:yclients_login")
async def admin_yclients_login_start(
    callback: CallbackQuery,
    state: FSMContext,
    services: ServiceContainer,
) -> None:
    await _ensure_admin(callback, services)
    if not await services.admin.is_yclients_configured():
        await _safe_edit_text(
            callback.message,
            "\n\n".join(
                [
                    bold("YCLIENTS НЕ НАСТРОЕН"),
                    blockquote("Сначала сохраните API key и Partner ID. После этого бот попросит логин и пароль."),
                ]
            ),
            reply_markup=admin_settings_keyboard(),
        )
        await callback.answer()
        return
    await state.clear()
    await state.set_state(AdminYClientsLoginStates.waiting_login)
    await _safe_edit_text(
        callback.message,
        _yclients_login_prompt_text(),
        reply_markup=yclients_login_cancel_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:yclients_login_cancel")
async def admin_yclients_login_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    services: ServiceContainer,
) -> None:
    await _ensure_admin(callback, services)
    await state.clear()
    await _safe_edit_text(callback.message, bold("НАСТРОЙКИ"), reply_markup=admin_settings_keyboard())
    await callback.answer()


@router.message(AdminYClientsLoginStates.waiting_login, F.text)
async def admin_yclients_login_text(
    message: Message,
    state: FSMContext,
    services: ServiceContainer,
) -> None:
    await services.admin.ensure_admin(message.from_user.id)
    login = (message.text or "").strip()
    if not login:
        await message.answer("Введите телефон или email от аккаунта YCLIENTS.", reply_markup=yclients_login_cancel_keyboard())
        return
    await state.update_data(yclients_login=login)
    await _try_delete(message)
    await state.set_state(AdminYClientsLoginStates.waiting_password)
    await message.answer(
        "\n\n".join(
            [
                bold("ПАРОЛЬ YCLIENTS"),
                blockquote(
                    [
                        "Отправьте пароль от аккаунта YCLIENTS следующим сообщением.",
                        "Сообщение с паролем будет удалено. В базе сохранится только User token, который вернёт YCLIENTS.",
                    ]
                ),
            ]
        ),
        reply_markup=yclients_login_cancel_keyboard(),
    )


@router.message(AdminYClientsLoginStates.waiting_password, F.text)
async def admin_yclients_password_text(
    message: Message,
    state: FSMContext,
    services: ServiceContainer,
) -> None:
    await services.admin.ensure_admin(message.from_user.id)
    data = await state.get_data()
    login = str(data.get("yclients_login") or "").strip()
    password = message.text or ""
    await _try_delete(message)
    if not login:
        await state.set_state(AdminYClientsLoginStates.waiting_login)
        await message.answer(_yclients_login_prompt_text(), reply_markup=yclients_login_cancel_keyboard())
        return
    if not password:
        await message.answer("Пароль не должен быть пустым.", reply_markup=yclients_login_cancel_keyboard())
        return

    async def connect_yclients():
        await services.admin.setup_yclients_login_password(login=login, password=password)
        await state.clear()
        text = "\n\n".join(
            [
                bold("ВХОД В YCLIENTS ВЫПОЛНЕН"),
                blockquote(
                    [
                        "User token получен и сохранён.",
                        "Статистика, записи, финансы и товары будут запрашиваться с правами этого аккаунта.",
                    ]
                ),
                await services.admin.check_connection_text(),
            ]
        )
        await message.answer(await services.admin.dashboard_text(), reply_markup=admin_main_keyboard())
        return text, None

    try:
        await answer_with_loading(
            message,
            title="ВХОД В YCLIENTS",
            detail="Получаю User token по логину и паролю.",
            producer=connect_yclients,
        )
    except AppError as exc:
        await message.answer(
            "\n\n".join(
                [
                    bold("YCLIENTS НЕ ПРИНЯЛ ВХОД"),
                    blockquote(
                        [
                            exc.public_message,
                            "Проверьте логин, пароль, доступ к филиалам и двухэтапную аутентификацию.",
                        ]
                    ),
                ]
            ),
            reply_markup=yclients_login_cancel_keyboard(),
        )


@router.callback_query(F.data == "admin:regulation")
async def admin_regulation(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await state.clear()
    await _safe_edit_text(
        callback.message,
        await services.admin.regulation_text(for_admin=True),
        reply_markup=admin_regulation_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:regulation_edit")
async def admin_regulation_edit(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await state.set_state(AdminRegulationStates.waiting_text)
    await _safe_edit_text(
        callback.message,
        "\n\n".join(
            [
                bold("РЕДАКТИРОВАНИЕ РЕГЛАМЕНТА"),
                blockquote(
                    "Отправьте новый текст регламента одним сообщением или загрузите PDF/DOCX файл. "
                    "Можно использовать форматирование Telegram: жирный текст, курсив, цитаты и списки. "
                    "Чтобы очистить регламент, отправьте -"
                ),
            ]
        ),
        reply_markup=admin_regulation_edit_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:regulation_cancel")
async def admin_regulation_cancel(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await state.clear()
    await _safe_edit_text(
        callback.message,
        await services.admin.regulation_text(for_admin=True),
        reply_markup=admin_regulation_keyboard(),
    )
    await callback.answer()


@router.message(AdminRegulationStates.waiting_text, F.document)
async def admin_regulation_document(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    document = message.document
    if document is None or not _is_regulation_document(document.file_name, document.mime_type):
        await message.answer(
            "Поддерживаются только PDF, DOC и DOCX.",
            reply_markup=admin_regulation_edit_keyboard(),
        )
        return
    caption = _regulation_message_html(message) if (message.caption or "").strip() else None
    if caption and len(caption) > 1000:
        await message.answer(
            "Подпись к файлу слишком длинная. Сократите её до 1000 символов.",
            reply_markup=admin_regulation_edit_keyboard(),
        )
        return
    await services.admin.update_regulation_file(
        file_id=document.file_id,
        file_name=document.file_name,
        caption=caption,
    )
    await state.clear()
    await message.answer(
        "\n\n".join(
            [
                bold("РЕГЛАМЕНТ СОХРАНЁН"),
                await services.admin.regulation_text(for_admin=True),
            ]
        ),
        reply_markup=admin_regulation_keyboard(),
    )


@router.message(AdminRegulationStates.waiting_text, F.text)
async def admin_regulation_text(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    raw_text = (message.text or "").strip()
    if _optional_token(raw_text) is None:
        saved_text = None
    else:
        saved_text = _regulation_message_html(message)
        if len(saved_text) > 3500:
            await message.answer(
                "Регламент слишком длинный. Сократите текст до 3500 символов.",
                reply_markup=admin_regulation_edit_keyboard(),
            )
            return
    await services.admin.update_regulation_text(saved_text)
    await state.clear()
    await message.answer(
        "\n\n".join(
            [
                bold("РЕГЛАМЕНТ СОХРАНЁН" if saved_text else "РЕГЛАМЕНТ ОЧИЩЕН"),
                await services.admin.regulation_text(for_admin=True),
            ]
        ),
        reply_markup=admin_regulation_keyboard(),
    )


@router.callback_query(F.data == "admin:kpi")
async def admin_kpi(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await state.clear()
    await _safe_edit_text(
        callback.message,
        await services.admin.kpi_settings_text(),
        reply_markup=admin_kpi_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:grade")
async def admin_grade(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await state.clear()
    await _safe_edit_text(
        callback.message,
        await services.admin.grade_settings_text(),
        reply_markup=admin_grade_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:franchisees")
async def admin_franchisees(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await state.clear()
    franchisees = await services.admin.list_franchisees()
    await _safe_edit_text(
        callback.message,
        _franchisees_text(franchisees),
        reply_markup=franchisees_keyboard(franchisees),
    )
    await callback.answer()


@router.callback_query(F.data == "franchise:invite")
async def admin_franchise_invite(callback: CallbackQuery, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    code = await services.admin.generate_franchise_invite(callback.from_user.id)
    bot_info = await callback.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={code}"
    franchisees = await services.admin.list_franchisees()
    await callback.message.answer(
        "\n\n".join(
            [
                bold("ССЫЛКА ДЛЯ РУКОВОДИТЕЛЯ ФИЛИАЛА"),
                pre(["Срок       7 дней", f"Код        {code}"]),
                f"Ссылка: {html_escape(link)}",
                blockquote(
                    [
                        "После перехода по ссылке человек подключится как руководитель филиала.",
                        "Доступ к вашим филиалам по умолчанию выключен. Его можно включить в карточке руководителя.",
                    ]
                ),
            ]
        ),
        reply_markup=franchisees_keyboard(franchisees),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("frt:"))
async def admin_franchise_global_toggle(callback: CallbackQuery, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    parts = callback.data.split(":")
    field_name = _FRANCHISE_GLOBAL_FIELDS.get(parts[1])
    if field_name is None:
        await callback.answer("Неизвестная настройка.", show_alert=True)
        return
    franchisee = await services.admin.toggle_franchisee_global_permission(UUID(parts[2]), field_name)
    branches = await services.admin.list_branches()
    await _safe_edit_text(callback.message, _franchisee_text(franchisee), reply_markup=franchisee_keyboard(franchisee, branches))
    await callback.answer()


@router.callback_query(F.data.startswith("frb:"))
async def admin_franchise_branch_toggle(callback: CallbackQuery, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    parts = callback.data.split(":")
    field_name = _FRANCHISE_BRANCH_FIELDS.get(parts[1])
    if field_name is None:
        await callback.answer("Неизвестная настройка.", show_alert=True)
        return
    branches = await services.admin.list_branches()
    try:
        branch = branches[int(parts[3])]
    except (IndexError, ValueError):
        await callback.answer("Филиал не найден. Откройте карточку заново.", show_alert=True)
        return
    franchisee = await services.admin.toggle_franchisee_branch_access(UUID(parts[2]), branch.id, field_name)
    await _safe_edit_text(callback.message, _franchisee_text(franchisee), reply_markup=franchisee_keyboard(franchisee, branches))
    await callback.answer()


@router.callback_query(F.data.startswith("franchise:"))
async def admin_franchise_callback(callback: CallbackQuery, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    parts = callback.data.split(":")
    action = parts[1]
    if action == "noop":
        await callback.answer()
        return
    if action == "toggle":
        field_name = parts[2]
        franchisee_id = UUID(parts[3])
        franchisee = await services.admin.toggle_franchisee_global_permission(franchisee_id, field_name)
        branches = await services.admin.list_branches()
        await _safe_edit_text(callback.message, _franchisee_text(franchisee), reply_markup=franchisee_keyboard(franchisee, branches))
    elif action == "branch":
        field_name = parts[2]
        franchisee_id = UUID(parts[3])
        branch_id = UUID(parts[4])
        franchisee = await services.admin.toggle_franchisee_branch_access(franchisee_id, branch_id, field_name)
        branches = await services.admin.list_branches()
        await _safe_edit_text(callback.message, _franchisee_text(franchisee), reply_markup=franchisee_keyboard(franchisee, branches))
    elif action == "block":
        franchisee = await services.admin.block_franchisee(UUID(parts[2]), blocked=True)
        branches = await services.admin.list_branches()
        await _safe_edit_text(callback.message, _franchisee_text(franchisee), reply_markup=franchisee_keyboard(franchisee, branches))
    elif action == "unblock":
        franchisee = await services.admin.block_franchisee(UUID(parts[2]), blocked=False)
        branches = await services.admin.list_branches()
        await _safe_edit_text(callback.message, _franchisee_text(franchisee), reply_markup=franchisee_keyboard(franchisee, branches))
    elif action == "delete":
        franchisee = await services.admin.get_franchisee(UUID(parts[2]))
        await _safe_edit_text(
            callback.message,
            "\n\n".join(
                [
                    bold("УДАЛИТЬ РУКОВОДИТЕЛЯ ФИЛИАЛА"),
                    pre([f"Имя {franchisee.title}", f"Статус {'заблокирован' if franchisee.is_blocked else 'активен'}"]),
                    blockquote("Доступ к боту будет отключён. Его филиалы в боте не удаляются."),
                ]
            ),
            reply_markup=franchise_delete_confirm_keyboard(franchisee.id),
        )
    elif action == "delete_confirm":
        deleted = await services.admin.delete_franchisee(UUID(parts[2]))
        franchisees = await services.admin.list_franchisees()
        await _safe_edit_text(
            callback.message,
            "\n\n".join([bold("РУКОВОДИТЕЛЬ ФИЛИАЛА УДАЛЁН"), blockquote(deleted.title)]),
            reply_markup=franchisees_keyboard(franchisees),
        )
    else:
        franchisee = await services.admin.get_franchisee(UUID(action))
        branches = await services.admin.list_branches()
        await _safe_edit_text(callback.message, _franchisee_text(franchisee), reply_markup=franchisee_keyboard(franchisee, branches))
    await callback.answer()


@router.callback_query(F.data == "admin:grade_edit")
async def admin_grade_edit(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await state.set_state(AdminGradeStates.waiting_rules)
    await _safe_edit_text(
        callback.message,
        "\n\n".join(
            [
                bold("ИЗМЕНЕНИЕ GRADE UP"),
                blockquote(
                    [
                        "Отправьте правила строками.",
                        "Формат: название = цена стрижки, средняя выручка/день, месяцев периода, минимальный стаж.",
                        "Пример:",
                        "Мастер = 1500, 12500, 2, 6",
                        "Старший мастер = 1700, 14500, 2, 6",
                        "Эксперт = 1900, 18000, 3, 12",
                    ]
                ),
            ]
        ),
        reply_markup=admin_grade_edit_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:grade_cancel")
async def admin_grade_cancel(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await state.clear()
    await _safe_edit_text(
        callback.message,
        await services.admin.grade_settings_text(),
        reply_markup=admin_grade_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:kpi_edit")
async def admin_kpi_edit(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await state.set_state(AdminKpiStates.waiting_rules)
    await _safe_edit_text(
        callback.message,
        "\n\n".join(
            [
                bold("ИЗМЕНЕНИЕ KPI"),
                blockquote(
                    [
                        "Отправьте правила строками: порог = процент.",
                        "Пример:",
                        "0 = 0",
                        "37000 = 2",
                        "60000 = 5",
                    ]
                ),
            ]
        ),
        reply_markup=admin_kpi_edit_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:kpi_cancel")
async def admin_kpi_cancel(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await state.clear()
    await _safe_edit_text(
        callback.message,
        await services.admin.kpi_settings_text(),
        reply_markup=admin_kpi_keyboard(),
    )
    await callback.answer()


@router.message(AdminKpiStates.waiting_rules, F.text)
async def admin_kpi_rules_text(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    try:
        await services.admin.update_kpi_rules_from_text(message.text or "")
    except AppError as exc:
        await message.answer(exc.public_message, reply_markup=admin_kpi_edit_keyboard())
        return
    await state.clear()
    await message.answer(
        "\n\n".join([bold("KPI СОХРАНЁН"), await services.admin.kpi_settings_text()]),
        reply_markup=admin_kpi_keyboard(),
    )


@router.message(AdminGradeStates.waiting_rules, F.text)
async def admin_grade_rules_text(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    try:
        await services.admin.update_grade_rules_from_text(message.text or "")
    except AppError as exc:
        await message.answer(exc.public_message, reply_markup=admin_grade_edit_keyboard())
        return
    await state.clear()
    await message.answer(
        "\n\n".join([bold("GRADE UP СОХРАНЁН"), await services.admin.grade_settings_text()]),
        reply_markup=admin_grade_keyboard(),
    )


@router.callback_query(F.data == "admin:reset")
async def admin_reset(callback: CallbackQuery, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await _safe_edit_text(
        callback.message,
        "\n\n".join(
            [
                bold("СБРОС ДО РЕГИСТРАЦИИ"),
                blockquote(
                    [
                        "Будут удалены филиалы, сотрудники, услуги, товары, статистика, подключения барберов, регламент и YCLIENTS-настройки.",
                        "Руководитель и пароль останутся.",
                    ]
                ),
            ]
        ),
        reply_markup=admin_reset_confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:reset_confirm")
async def admin_reset_confirm(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    await state.clear()
    await services.admin.reset_to_registration()
    await _safe_edit_text(
        callback.message,
        "\n\n".join(
            [
                bold("СБРОС ВЫПОЛНЕН"),
                blockquote(
                    "Бот вернулся к первому запуску. Нажмите /admin и зарегистрируйтесь как руководитель заново."
                ),
            ]
        )
    )
    await callback.answer()


@router.message(AdminCompanySetupStates.waiting_api_key, F.text)
async def setup_yclients_api_key(message: Message, state: FSMContext) -> None:
    await state.update_data(api_key=message.text.strip())
    await _try_delete(message)
    await state.set_state(AdminCompanySetupStates.waiting_partner_id)
    await message.answer("Введите Partner ID.")


@router.message(AdminCompanySetupStates.waiting_partner_id, F.text)
async def setup_yclients_partner_id(
    message: Message,
    state: FSMContext,
    services: ServiceContainer,
) -> None:
    try:
        partner_id = int(message.text.strip())
    except ValueError:
        await message.answer("Partner ID должен быть числом.")
        return
    data = await state.get_data()
    try:
        company = await services.admin.setup_yclients(
            api_key=data["api_key"],
            partner_id=partner_id,
            user_token=None,
        )
    except AppError as exc:
        await message.answer(exc.public_message)
        return
    await _try_delete(message)
    await state.clear()
    await state.set_state(AdminYClientsLoginStates.waiting_login)
    await message.answer(
        "\n\n".join(
            [
                bold("YCLIENTS ОСНОВА СОХРАНЕНА"),
                pre([f"Partner ID {company.partner_id}", "User token ❌ нужно получить"]),
                _yclients_login_prompt_text(),
            ]
        ),
        reply_markup=yclients_login_cancel_keyboard(),
    )


@router.message(AdminCompanySetupStates.waiting_user_token, F.text)
async def setup_yclients_user_token(
    message: Message,
    state: FSMContext,
    services: ServiceContainer,
) -> None:
    data = await state.get_data()
    user_token = _optional_token(message.text)
    if data.get("setup_mode") == "user_token_only":
        try:
            await services.admin.setup_yclients_user_token(user_token)
        except AppError as exc:
            await message.answer(exc.public_message)
            return
        await _try_delete(message)
        await state.clear()
        await message.answer(
            "\n\n".join(
                [
                    bold("USER TOKEN СОХРАНЁН" if user_token else "USER TOKEN ОЧИЩЕН"),
                    blockquote("Теперь товары и статистика будут использовать обновлённые данные доступа."),
                ]
            ),
            reply_markup=admin_main_keyboard(),
        )
        return
    data = await state.get_data()
    company = await services.admin.setup_yclients(
        api_key=data["api_key"],
        partner_id=data["partner_id"],
        user_token=user_token,
    )
    await _try_delete(message)
    await state.clear()
    await message.answer(
        "\n\n".join(
            [
                bold("YCLIENTS СОХРАНЁН"),
                pre(
                    [
                        f"Partner ID {company.partner_id}",
                        f"User token {'✅ указан' if user_token else '❌ пропущен'}",
                    ]
                ),
                blockquote(
                    "Филиалы пока не добавлены. Перейдите в «Филиалы» и добавьте первый филиал. "
                    "Для проверки доступа используйте кнопку «Проверка подключения»."
                ),
            ]
        ),
        reply_markup=admin_main_keyboard(),
    )


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_manager(callback, services)
    await state.clear()
    branches = await services.admin.list_visible_branches(callback.from_user.id)
    if not branches:
        await _safe_edit_text(
            callback.message,
            "\n\n".join(
                [
                    bold("ДЕЙСТВИЯ ДЛЯ БАРБЕРОВ"),
                    blockquote("Сначала добавьте филиал и синхронизируйте сотрудников."),
                ]
            ),
            reply_markup=None,
        )
        await callback.answer()
        return
    if len(branches) == 1:
        await _show_broadcast_actions(callback.message, state, services, branches[0].id, actor_id=callback.from_user.id)
    else:
        await state.set_state(AdminBroadcastStates.choosing_branch)
        await _safe_edit_text(
            callback.message,
            "\n\n".join(
                [
                    bold("ДЕЙСТВИЯ ДЛЯ БАРБЕРОВ"),
                    blockquote("Выберите филиал или отправьте действие всем подключённым сотрудникам."),
                ]
            ),
            reply_markup=broadcast_branch_keyboard(branches),
        )
    await callback.answer()


@router.callback_query(F.data == "broadcast:cancel")
async def admin_broadcast_cancel(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_manager(callback, services)
    await state.clear()
    await _safe_edit_text(
        callback.message,
        "\n\n".join([bold("РАССЫЛКА ОТМЕНЕНА"), blockquote("Действие не отправлено сотрудникам.")]),
        reply_markup=None,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("broadcast:branch:"))
async def admin_broadcast_branch(callback: CallbackQuery, state: FSMContext, services: ServiceContainer) -> None:
    await _ensure_manager(callback, services)
    branch_value = callback.data.split(":", maxsplit=2)[2]
    branch_id = None if branch_value == "all" else UUID(branch_value)
    await _show_broadcast_actions(callback.message, state, services, branch_id, actor_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "broadcast:action:message")
async def admin_broadcast_message_action(
    callback: CallbackQuery,
    state: FSMContext,
    services: ServiceContainer,
) -> None:
    await _ensure_manager(callback, services)
    await state.set_state(AdminBroadcastStates.waiting_message_text)
    scope, targets_count = await _broadcast_scope_summary(state, services, callback.from_user.id)
    await _safe_edit_text(
        callback.message,
        "\n\n".join(
            [
                bold("СООБЩЕНИЕ БАРБЕРАМ"),
                pre([f"Кому       {scope}", f"Получателей {targets_count}"]),
                blockquote("Отправьте текст сообщения следующим сообщением."),
            ]
        ),
        reply_markup=broadcast_cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminBroadcastStates.waiting_message_text, Command("cancel"))
async def admin_broadcast_message_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "\n\n".join([bold("РАССЫЛКА ОТМЕНЕНА"), blockquote("Действие не отправлено сотрудникам.")]),
        reply_markup=admin_main_keyboard(),
    )


@router.message(AdminBroadcastStates.waiting_message_text, F.text)
async def admin_broadcast_message_text(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    text = message.text.strip()
    if not text:
        await message.answer("Сообщение не должно быть пустым.", reply_markup=broadcast_cancel_keyboard())
        return
    message_html = _message_html_as_blockquote(message)
    if len(message_html) > 3500:
        await message.answer("Сообщение слишком длинное. Сократите текст до 3500 символов.", reply_markup=broadcast_cancel_keyboard())
        return
    await state.update_data(message_text=message_html)
    await state.set_state(AdminBroadcastStates.confirming_message)
    scope, targets_count = await _broadcast_scope_summary(state, services, message.from_user.id)
    await message.answer(
        "\n\n".join(
            [
                bold("ПОДТВЕРДИТЕ РАССЫЛКУ"),
                pre([f"Тип        сообщение", f"Кому       {scope}", f"Получателей {targets_count}"]),
                _admin_broadcast_text(message_html),
            ]
        ),
        reply_markup=broadcast_confirm_keyboard("message"),
    )


@router.callback_query(F.data == "broadcast:action:stats")
async def admin_broadcast_statistics_action(
    callback: CallbackQuery,
    state: FSMContext,
    services: ServiceContainer,
) -> None:
    await _ensure_manager(callback, services)
    await state.set_state(AdminBroadcastStates.confirming_statistics)
    scope, targets_count = await _broadcast_scope_summary(state, services, callback.from_user.id)
    await _safe_edit_text(
        callback.message,
        "\n\n".join(
            [
                bold("СТАТИСТИКА ЗА ТЕКУЩИЙ МЕСЯЦ"),
                pre([f"Кому       {scope}", f"Получателей {targets_count}", *_period_lines("month")]),
                blockquote("Каждый подключённый сотрудник получит свою личную статистику за указанный период."),
            ]
        ),
        reply_markup=broadcast_confirm_keyboard("stats"),
    )
    await callback.answer()


@router.callback_query(F.data == "broadcast:confirm:message")
async def admin_broadcast_confirm_message(
    callback: CallbackQuery,
    state: FSMContext,
    services: ServiceContainer,
) -> None:
    await _ensure_manager(callback, services)
    data = await state.get_data()
    message_text = data.get("message_text")
    if not message_text:
        await callback.answer("Текст сообщения не найден. Начните рассылку заново.", show_alert=True)
        return
    await callback.answer()

    async def send_message_broadcast():
        targets = await _broadcast_targets_from_state(state, services, callback.from_user.id)
        sent, failed = await _send_text_to_targets(callback, targets, _admin_broadcast_text(message_text))
        await state.clear()
        return _broadcast_result_text("СООБЩЕНИЕ ОТПРАВЛЕНО", len(targets), sent, failed), None

    await edit_with_loading(
        callback.message,
        title="ОТПРАВКА СООБЩЕНИЯ",
        detail="Рассылаю сообщение подключённым сотрудникам.",
        producer=send_message_broadcast,
    )


@router.callback_query(F.data == "broadcast:confirm:stats")
async def admin_broadcast_confirm_statistics(
    callback: CallbackQuery,
    state: FSMContext,
    services: ServiceContainer,
) -> None:
    await _ensure_manager(callback, services)
    await callback.answer()

    async def send_statistics_broadcast():
        targets = await _broadcast_targets_from_state(state, services, callback.from_user.id)
        with suppress(Exception):
            await services.statistics.refresh_team_period(targets, "month")
        sent = 0
        failed = 0
        for employee in targets:
            try:
                fallback_text = await services.statistics.employee_stats_text(employee, "month", refresh=False)
                rich_message = await services.statistics.employee_stats_rich_message(employee, "month")
                try:
                    await callback.bot.send_rich_message(
                        chat_id=employee.telegram_user.telegram_id,
                        rich_message=rich_message,
                    )
                except Exception:
                    await callback.bot.send_message(employee.telegram_user.telegram_id, fallback_text)
                sent += 1
            except Exception:
                failed += 1
        await state.clear()
        return _broadcast_result_text("СТАТИСТИКА ОТПРАВЛЕНА", len(targets), sent, failed), None

    await edit_with_loading(
        callback.message,
        title="ОТПРАВКА СТАТИСТИКИ",
        detail="Собираю текущий месяц и отправляю каждому сотруднику.",
        producer=send_statistics_broadcast,
    )


@router.callback_query(F.data.startswith("branch:"))
async def branch_callback(callback: CallbackQuery, services: ServiceContainer) -> None:
    await _ensure_manager(callback, services)
    parts = callback.data.split(":")
    action = parts[1]
    if action == "employees":
        branch_id = UUID(parts[2])
        await callback.answer()

        async def load_branch_employees():
            branch = await services.admin.get_visible_branch(branch_id, callback.from_user.id)
            branch = await services.admin.check_branch_connection(branch.id)
            employees = await services.admin.get_branch_employees(branch.id)
            return RichMessageResult(
                rich_message=_employees_rich_message(employees),
                fallback_text=_employees_text(employees),
                reply_markup=employees_keyboard(branch.id, employees),
            )

        await edit_with_loading(
            callback.message,
            title="ОБНОВЛЕНИЕ СОТРУДНИКОВ",
            detail="Сверяю список с актуальными данными YCLIENTS.",
            producer=load_branch_employees,
        )
        return
    elif action == "check":
        branch_id = UUID(parts[2])
        await callback.answer()

        async def check_branch():
            branch = await services.admin.get_visible_branch(branch_id, callback.from_user.id)
            branch = await services.admin.check_branch_connection(branch.id)
            return await services.admin.branch_details_text(branch), branch_dashboard_keyboard(branch.id)

        await edit_with_loading(
            callback.message,
            title="ПРОВЕРКА ФИЛИАЛА",
            detail="Обновляю сотрудников и услуги.",
            producer=check_branch,
        )
        return
    elif action == "stats":
        period, branch_id = _branch_period_and_id(parts, default_period="month")
        branch = await services.admin.get_visible_branch(branch_id, callback.from_user.id)
        await callback.answer()

        async def load_branch_stats():
            employees = await services.admin.get_branch_employees(branch.id)
            try:
                await services.statistics.refresh_team_period(employees, period)
            except Exception:
                pass
            return RichMessageResult(
                rich_message=await services.statistics.team_stats_rich_message(employees, period, title=branch.name),
                fallback_text=await services.statistics.team_stats_text(employees, period, title=branch.name, refresh=False),
                reply_markup=branch_stats_period_keyboard(branch.id, period),
            )

        await edit_with_loading(
            callback.message,
            title="ЗАГРУЗКА СТАТИСТИКИ",
            detail="Собираю данные сотрудников филиала.",
            producer=load_branch_stats,
        )
        return
    elif action == "kpi":
        branch_id = UUID(parts[2])
        branch = await services.admin.get_visible_branch(branch_id, callback.from_user.id)
        await callback.answer()

        async def load_branch_kpi():
            employees = await services.admin.get_branch_employees(branch.id)
            try:
                await services.statistics.refresh_team_period(employees, "month")
            except Exception:
                pass
            return RichMessageResult(
                rich_message=await services.kpi.team_kpi_rich_message(employees, title=branch.name),
                fallback_text=await services.kpi.team_kpi_text(employees, title=branch.name, refresh=False),
                reply_markup=branch_dashboard_keyboard(branch.id),
            )

        await edit_with_loading(
            callback.message,
            title="ЗАГРУЗКА KPI",
            detail="Собираю KPI сотрудников филиала.",
            producer=load_branch_kpi,
        )
        return
    elif action == "delete":
        branch_id = UUID(parts[2])
        branch = await services.admin.ensure_can_delete_branch(branch_id, callback.from_user.id)
        await _safe_edit_text(
            callback.message,
            "\n\n".join(
                [
                    bold("УДАЛИТЬ ФИЛИАЛ"),
                    pre(
                        [
                            f"Филиал {branch.name}",
                            f"ID     {branch.yclients_branch_id}",
                        ]
                    ),
                    blockquote("Будут удалены сотрудники, услуги, статистика и подключения внутри этого филиала."),
                ]
            ),
            reply_markup=branch_delete_confirm_keyboard(branch.id),
        )
    elif action == "delete_confirm":
        branch_id = UUID(parts[2])
        await services.admin.ensure_can_delete_branch(branch_id, callback.from_user.id)
        deleted_branch = await services.admin.delete_branch(branch_id)
        branches = await services.admin.list_visible_branches(callback.from_user.id)
        await _safe_edit_text(
            callback.message,
            "\n\n".join(
                [
                    bold("ФИЛИАЛ УДАЛЁН"),
                    blockquote(f"{deleted_branch.name} удалён из бота."),
                ]
            ),
            reply_markup=branches_keyboard(branches) if branches else None,
        )
    else:
        branch_id = UUID(action)
        branch = await services.admin.get_visible_branch(branch_id, callback.from_user.id)
        await _safe_edit_text(
            callback.message,
            await services.admin.branch_details_text(branch),
            reply_markup=branch_dashboard_keyboard(branch.id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:team_stats:"))
async def admin_team_stats(callback: CallbackQuery, services: ServiceContainer) -> None:
    await _ensure_manager(callback, services)
    period = callback.data.split(":", maxsplit=2)[2]
    await callback.answer()

    async def load_team_stats():
        employees = await services.admin.get_visible_team_employees(callback.from_user.id)
        try:
            await services.statistics.refresh_team_period(employees, period)
        except Exception:
            pass
        return RichMessageResult(
            rich_message=await services.statistics.team_stats_rich_message(employees, period, title="вся команда"),
            fallback_text=await services.statistics.team_stats_text(employees, period, title="вся команда", refresh=False),
            reply_markup=team_stats_period_keyboard(period),
        )

    await edit_with_loading(
        callback.message,
        title="ЗАГРУЗКА СТАТИСТИКИ",
        detail="Собираю данные по всем сотрудникам.",
        producer=load_team_stats,
    )


@router.callback_query(F.data.startswith("employee:"))
async def employee_admin_callback(callback: CallbackQuery, services: ServiceContainer) -> None:
    await _ensure_manager(callback, services)
    parts = callback.data.split(":")
    action = parts[1]
    employee_id = UUID(parts[2] if len(parts) > 2 else parts[1])
    employee = await services.admin.get_visible_employee(employee_id, callback.from_user.id)

    if action == "code":
        code = await services.connection.generate_code(employee.id)
        bot_info = await callback.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={code}"
        sent_message = await callback.message.answer(
            "\n\n".join(
                [
                    bold("КОД ПОДКЛЮЧЕНИЯ"),
                    pre([f"Сотрудник {employee.full_name}", f"Код       {code}"]),
                    f"Ссылка: {html_escape(link)}",
                    blockquote("Срок действия: 15 минут. Отправьте сотруднику код или ссылку."),
                ]
            )
        )
        await services.connection.attach_code_admin_message(
            code,
            chat_id=sent_message.chat.id,
            message_id=sent_message.message_id,
        )
    elif action == "disconnect":
        employee = await services.connection.disconnect_employee(employee.id)
        await _safe_edit_text(callback.message, _employee_text(employee), reply_markup=employee_admin_keyboard(employee))
    elif action == "stats":
        await callback.answer()

        async def load_employee_stats() -> RichMessageResult:
            try:
                await services.statistics.refresh_period(employee, "month")
            except Exception:
                pass
            return RichMessageResult(
                rich_message=await services.statistics.employee_stats_rich_message(employee, "month"),
                fallback_text=await services.statistics.employee_stats_text(employee, "month", refresh=False),
            )

        await answer_with_loading(
            callback.message,
            title="ЗАГРУЗКА СТАТИСТИКИ",
            detail="Обновляю месяц сотрудника.",
            producer=load_employee_stats,
        )
        return
    else:
        await _safe_edit_text(callback.message, _employee_text(employee), reply_markup=employee_admin_keyboard(employee))
    await callback.answer()


@router.callback_query(F.data.in_({"admin:check_connection", "admin:settings", "admin:statistics_settings"}))
async def admin_misc(callback: CallbackQuery, services: ServiceContainer) -> None:
    await _ensure_admin(callback, services)
    if callback.data == "admin:check_connection":
        await callback.answer()

        async def check_connection():
            text = await services.admin.check_connection_text()
            try:
                available, existing_ids = await services.admin.available_branches()
                keyboard = available_branches_keyboard(available, existing_ids)
            except Exception:
                keyboard = None
            return text, keyboard

        await edit_with_loading(
            callback.message,
            title="ПРОВЕРКА YCLIENTS",
            detail="Запрашиваю доступные филиалы.",
            producer=check_connection,
        )
        return
    elif callback.data == "admin:statistics_settings":
        await _safe_edit_text(
            callback.message,
            "\n\n".join(
                [
                    bold("НАСТРОЙКИ СТАТИСТИКИ"),
                    blockquote("Отчёты отправляются по расписанию из .env и настроек компании."),
                ]
            ),
            reply_markup=None,
        )
    elif callback.data == "admin:settings":
        await _safe_edit_text(
            callback.message,
            bold("НАСТРОЙКИ"),
            reply_markup=admin_settings_keyboard(),
        )
    else:
        await _safe_edit_text(
            callback.message,
            "\n\n".join([bold("НАСТРОЙКИ СТАТИСТИКИ"), blockquote("Настройки статистики обновляются через .env.")]),
            reply_markup=None,
        )
    await callback.answer()


async def _ensure_admin(callback: CallbackQuery, services: ServiceContainer) -> None:
    await services.admin.ensure_admin(callback.from_user.id)


async def _ensure_manager(callback: CallbackQuery, services: ServiceContainer) -> None:
    await services.admin.ensure_manager(callback.from_user.id)


async def _try_delete(message: Message) -> None:
    with suppress(Exception):
        await message.delete()


async def _safe_edit_text(message: Message, text: str, *, reply_markup=None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


def _branch_text(branch) -> str:
    return "\n\n".join(
        [
            bold(branch.name.upper()),
            pre(
                [
                    f"ID филиала       {branch.yclients_branch_id}",
                    f"Статус проверки  {branch.sync_status.value}",
                    f"Сотрудников      {branch.employees_count}",
                    f"Последняя проверка {branch.last_synced_at or 'ещё не было'}",
                ]
            ),
        ]
    )


def _branches_text(branches) -> str:
    if not branches:
        return "\n\n".join([bold("ФИЛИАЛЫ"), blockquote("Филиалы ещё не добавлены.")])
    return "\n\n".join(
        [
            bold("ФИЛИАЛЫ"),
            pre(
                [
                    f"{shorten(branch.name, 26):26} {branch.yclients_branch_id:<8} {branch.sync_status.value}"
                    for branch in branches
                ]
            ),
        ]
    )


def _employees_text(employees) -> str:
    if not employees:
        return "\n\n".join([bold("СОТРУДНИКИ"), blockquote("Сотрудники пока не синхронизированы.")])
    connected = sum(1 for employee in employees if employee.telegram_user_id)
    lines = [f"{'':1} {'Имя':20} {'Грейд':14} Telegram"]
    for employee in employees:
        marker = "✅" if employee.telegram_user_id else "❌"
        lines.append(
            f"{marker} {shorten(employee.full_name, 20):20} "
            f"{shorten(employee.category_title or 'без грейда', 14):14} "
            f"{_telegram_label(employee)}"
        )
    return "\n\n".join(
        [
            bold("СОТРУДНИКИ"),
            blockquote([f"✅ подключены: {connected}", f"❌ не подключены: {len(employees) - connected}"]),
            pre(lines),
        ]
    )


def _employees_rich_message(employees):
    if not employees:
        return rich_message("СОТРУДНИКИ", table(table_rows(["Статус"], [["Сотрудники пока не синхронизированы."]])))
    rows = [
        [
            "✅" if employee.telegram_user_id else "❌",
            employee.full_name,
            employee.category_title or "без грейда",
            _telegram_label(employee),
        ]
        for employee in employees
    ]
    return rich_message(
        "СОТРУДНИКИ",
        table(table_rows(["", "Имя", "Грейд", "Telegram"], rows)),
    )


def _franchisees_text(franchisees) -> str:
    if not franchisees:
        return "\n\n".join(
            [
                bold("РУКОВОДИТЕЛИ ФИЛИАЛОВ"),
                blockquote("Пока никто не подключён. Создайте ссылку и отправьте её будущему руководителю филиала."),
            ]
        )
    active = sum(1 for franchisee in franchisees if not franchisee.is_blocked)
    return "\n\n".join(
        [
            bold("РУКОВОДИТЕЛИ ФИЛИАЛОВ"),
            pre([f"Активные     {active}", f"Заблокированы {len(franchisees) - active}", f"Всего        {len(franchisees)}"]),
        ]
    )


def _franchisee_text(franchisee) -> str:
    telegram = "-"
    if franchisee.telegram_user and franchisee.telegram_user.username:
        telegram = f"@{franchisee.telegram_user.username}"
    elif franchisee.telegram_user:
        telegram = "Telegram"
    branch_lines = []
    for access in franchisee.branch_accesses:
        if not access.branch:
            continue
        branch_lines.append(
            f"{shorten(access.branch.name, 20):20} "
            f"{'✅' if access.can_view_statistics else '❌'} стат "
            f"{'✅' if access.can_message_employees else '❌'} сообщ "
            f"{'✅' if access.can_manage_employees else '❌'} упр"
        )
    return "\n\n".join(
        [
            bold(franchisee.title.upper()),
            pre(
                [
                    f"Telegram    {telegram}",
                    f"Статус      {'❌ заблокирован' if franchisee.is_blocked else '✅ активен'}",
                    f"Филиалы     {'✅ все филиалы руководителя' if franchisee.can_view_owner_branches else '❌ только выданные/свои'}",
                    f"Сообщения   {'✅ разрешены' if franchisee.can_message_owner_employees else '❌ запрещены'}",
                    f"Статистика  {'✅ разрешена' if franchisee.can_receive_owner_statistics else '❌ запрещена'}",
                ]
            ),
            pre(["Доступы по филиалам", *(branch_lines or ["пока не выданы"])]),
        ]
    )


def _employee_text(employee) -> str:
    status = "✅ подключён" if employee.telegram_user_id else "❌ не подключён"
    return "\n\n".join(
        [
            bold(employee.full_name.upper()),
            pre(
                [
                    f"Telegram   {_telegram_label(employee)}",
                    f"Статус     {status}",
                    f"Категория  {employee.category_title or 'не указана'}",
                    f"Staff ID   {employee.yclients_staff_id}",
                ]
            ),
        ]
    )


def _telegram_label(employee) -> str:
    if not employee.telegram_user_id:
        return "-"
    if employee.telegram_user and employee.telegram_user.username:
        return f"@{employee.telegram_user.username}"
    return "Telegram"


async def _show_broadcast_actions(
    message: Message,
    state: FSMContext,
    services: ServiceContainer,
    branch_id: UUID | None,
    *,
    actor_id: int,
    edit: bool = True,
) -> None:
    await state.update_data(broadcast_branch_id=str(branch_id) if branch_id else None)
    await state.set_state(AdminBroadcastStates.choosing_action)
    scope, targets_count = await _broadcast_scope_summary(state, services, actor_id)
    text = "\n\n".join(
        [
            bold("ДЕЙСТВИЯ ДЛЯ БАРБЕРОВ"),
            pre([f"Кому       {scope}", f"Получателей {targets_count}"]),
            blockquote("Выберите действие. Получателями будут только сотрудники с подключённым Telegram."),
        ]
    )
    if edit:
        await _safe_edit_text(message, text, reply_markup=broadcast_action_keyboard())
    else:
        await message.answer(text, reply_markup=broadcast_action_keyboard())


async def _broadcast_scope_summary(state: FSMContext, services: ServiceContainer, actor_id: int) -> tuple[str, int]:
    branch_id = await _broadcast_branch_id_from_state(state)
    targets = await services.admin.get_visible_broadcast_targets(actor_id, branch_id)
    if branch_id is None:
        return "все филиалы", len(targets)
    branch = await services.admin.get_branch(branch_id)
    return branch.name, len(targets)


async def _broadcast_targets_from_state(state: FSMContext, services: ServiceContainer, actor_id: int):
    branch_id = await _broadcast_branch_id_from_state(state)
    return await services.admin.get_visible_broadcast_targets(actor_id, branch_id)


async def _broadcast_branch_id_from_state(state: FSMContext) -> UUID | None:
    data = await state.get_data()
    branch_id = data.get("broadcast_branch_id")
    return UUID(branch_id) if branch_id else None


async def _send_text_to_targets(callback: CallbackQuery, targets, text: str) -> tuple[int, int]:
    sent = 0
    failed = 0
    for employee in targets:
        try:
            await callback.bot.send_message(employee.telegram_user.telegram_id, text)
            sent += 1
        except Exception:
            failed += 1
    return sent, failed


def _admin_broadcast_text(text: str) -> str:
    return "\n\n".join([bold("СООБЩЕНИЕ ОТ РУКОВОДИТЕЛЯ"), text])


def _broadcast_result_text(title: str, targets_count: int, sent: int, failed: int) -> str:
    return "\n\n".join(
        [
            bold(title),
            pre(
                [
                    f"Получателей {targets_count}",
                    f"Отправлено  {sent}",
                    f"Ошибок      {failed}",
                ]
            ),
        ]
    )


def _optional_token(text: str | None) -> str | None:
    value = (text or "").strip()
    if value.casefold() in {"", "-", "нет", "no", "skip", "пропустить"}:
        return None
    return value


def _yclients_login_prompt_text() -> str:
    return "\n\n".join(
        [
            bold("ВХОД В YCLIENTS"),
            blockquote(
                [
                    "Введите телефон или email от аккаунта YCLIENTS.",
                    "Телефон лучше указывать с кодом страны, например 7XXXXXXXXXX.",
                    "После этого бот попросит пароль, получит User token и сохранит только токен.",
                ]
            ),
        ]
    )


def _regulation_message_html(message: Message) -> str:
    return _message_html_as_blockquote(message)


def _is_regulation_document(file_name: str | None, mime_type: str | None) -> bool:
    name = (file_name or "").casefold()
    mime = (mime_type or "").casefold()
    if name.endswith((".pdf", ".doc", ".docx")):
        return True
    return mime in {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }


def _message_html_as_blockquote(message: Message) -> str:
    text = (getattr(message, "html_text", None) or html_escape(message.text or message.caption or "")).strip()
    if "<blockquote" in text:
        return text
    return f"<blockquote>{text}</blockquote>"


def _branch_period_and_id(parts: list[str], *, default_period: str) -> tuple[str, UUID]:
    if len(parts) >= 4:
        return parts[2], UUID(parts[3])
    return default_period, UUID(parts[2])
