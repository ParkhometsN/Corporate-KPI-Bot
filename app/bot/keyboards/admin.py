from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Branch, Employee


def admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏢 Филиалы", callback_data="admin:branches")],
            [InlineKeyboardButton(text="📊 Статистика команды", callback_data="admin:team_stats:month")],
            [InlineKeyboardButton(text="📣 Действия для барберов", callback_data="admin:broadcast")],
            [InlineKeyboardButton(text="📋 Регламент", callback_data="admin:regulation")],
            [InlineKeyboardButton(text="📊 Настройки статистики", callback_data="admin:statistics_settings")],
            [InlineKeyboardButton(text="🎯 KPI", callback_data="admin:kpi")],
            [InlineKeyboardButton(text="⚙ Настройки", callback_data="admin:settings")],
            [InlineKeyboardButton(text="✅ Проверка подключения", callback_data="admin:check_connection")],
        ]
    )


def available_branches_keyboard(available_branches: list, existing_branch_ids: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for branch in available_branches[:30]:
        if branch.id in existing_branch_ids:
            rows.append(
                [InlineKeyboardButton(text=f"✅ {branch.title}", callback_data=f"available_branch:exists:{branch.id}")]
            )
        else:
            rows.append(
                [InlineKeyboardButton(text=f"➕ {branch.title}", callback_data=f"available_branch:add:{branch.id}")]
            )
    rows.append([InlineKeyboardButton(text="✍️ Ввести ID вручную", callback_data="admin:add_branch")])
    rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data="admin:dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Обновить YCLIENTS", callback_data="admin:setup_yclients")],
            [InlineKeyboardButton(text="👤 Обновить User token", callback_data="admin:setup_user_token")],
            [InlineKeyboardButton(text="📋 Регламент", callback_data="admin:regulation")],
            [InlineKeyboardButton(text="🧨 Сброс до регистрации", callback_data="admin:reset")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="admin:dashboard")],
        ]
    )


def admin_regulation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Изменить регламент", callback_data="admin:regulation_edit")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="admin:dashboard")],
        ]
    )


def admin_regulation_edit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:regulation_cancel")],
        ]
    )


def admin_kpi_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Изменить правила KPI", callback_data="admin:kpi_edit")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="admin:dashboard")],
        ]
    )


def admin_kpi_edit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:kpi_cancel")],
        ]
    )


def admin_reset_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, сбросить", callback_data="admin:reset_confirm")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:settings")],
        ]
    )


def broadcast_branch_keyboard(branches: list[Branch]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Все филиалы", callback_data="broadcast:branch:all")]]
    rows.extend(
        [InlineKeyboardButton(text=branch.name, callback_data=f"broadcast:branch:{branch.id}")]
        for branch in branches
    )
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Отправить сообщение", callback_data="broadcast:action:message")],
            [InlineKeyboardButton(text="📊 Статистика за прошлый месяц", callback_data="broadcast:action:stats")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel")],
        ]
    )


def broadcast_confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отправить", callback_data=f"broadcast:confirm:{action}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel")],
        ]
    )


def broadcast_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel")],
        ]
    )


def branches_keyboard(branches: list[Branch]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"🏢 {branch.name}", callback_data=f"branch:{branch.id}")]
        for branch in branches
    ]
    rows.append([InlineKeyboardButton(text="✅ Показать доступные филиалы", callback_data="admin:available_branches")])
    rows.append([InlineKeyboardButton(text="➕ Добавить филиал", callback_data="admin:add_branch")])
    rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data="admin:dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def branch_dashboard_keyboard(branch_id: UUID) -> InlineKeyboardMarkup:
    branch = str(branch_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Сотрудники", callback_data=f"branch:employees:{branch}")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data=f"branch:stats:month:{branch}")],
            [InlineKeyboardButton(text="🎯 KPI", callback_data=f"branch:kpi:{branch}")],
            [InlineKeyboardButton(text="✅ Проверка подключения", callback_data=f"branch:check:{branch}")],
            [InlineKeyboardButton(text="🗑 Удалить филиал", callback_data=f"branch:delete:{branch}")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="admin:branches")],
        ]
    )


def branch_delete_confirm_keyboard(branch_id: UUID) -> InlineKeyboardMarkup:
    branch = str(branch_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить филиал", callback_data=f"branch:delete_confirm:{branch}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"branch:{branch}")],
        ]
    )


def employees_keyboard(branch_id: UUID, employees: list[Employee]) -> InlineKeyboardMarkup:
    rows = []
    for employee in employees:
        if employee.telegram_user:
            username = f" @{employee.telegram_user.username}" if employee.telegram_user.username else ""
            text = f"✅ {employee.full_name}{username}"
        else:
            text = f"❌ {employee.full_name}"
        rows.append(
            [InlineKeyboardButton(text=text, callback_data=f"employee:{employee.id}")]
        )
    rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data=f"branch:{branch_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def employee_admin_keyboard(employee: Employee) -> InlineKeyboardMarkup:
    employee_id = str(employee.id)
    rows = []
    if employee.telegram_user_id:
        rows.extend(
            [
                [InlineKeyboardButton(text="📊 Смотреть статистику", callback_data=f"employee:stats:{employee_id}")],
                [InlineKeyboardButton(text="🔁 Переподключить Telegram", callback_data=f"employee:code:{employee_id}")],
                [InlineKeyboardButton(text="⛔ Отключить", callback_data=f"employee:disconnect:{employee_id}")],
            ]
        )
    else:
        rows.append(
                [InlineKeyboardButton(text="🔐 Подключить сотрудника", callback_data=f"employee:code:{employee_id}")]
        )
    rows.append([InlineKeyboardButton(text="⬅ Назад к филиалам", callback_data="admin:branches")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def branch_stats_period_keyboard(branch_id: UUID, selected_period: str) -> InlineKeyboardMarkup:
    branch = str(branch_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            _period_buttons("branch:stats", branch, selected_period),
            [InlineKeyboardButton(text="⬅ Назад к филиалу", callback_data=f"branch:{branch}")],
        ]
    )


def team_stats_period_keyboard(selected_period: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            _period_buttons("admin:team_stats", None, selected_period),
            [InlineKeyboardButton(text="⬅ Назад", callback_data="admin:dashboard")],
        ]
    )


def _period_buttons(prefix: str, branch: str | None, selected_period: str) -> list[InlineKeyboardButton]:
    periods = (("today", "День"), ("week", "Неделя"), ("month", "Месяц"))
    buttons = []
    for period, title in periods:
        marker = "✅ " if period == selected_period else ""
        callback_data = f"{prefix}:{period}:{branch}" if branch else f"{prefix}:{period}"
        buttons.append(InlineKeyboardButton(text=f"{marker}{title}", callback_data=callback_data))
    return buttons
