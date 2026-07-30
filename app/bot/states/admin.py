from aiogram.fsm.state import State, StatesGroup


class AdminAuthStates(StatesGroup):
    waiting_password = State()
    waiting_initial_password = State()


class AdminBranchStates(StatesGroup):
    waiting_branch_id = State()


class AdminCompanySetupStates(StatesGroup):
    waiting_api_key = State()
    waiting_partner_id = State()
    waiting_user_token = State()


class AdminYClientsLoginStates(StatesGroup):
    waiting_login = State()
    waiting_password = State()


class AdminBroadcastStates(StatesGroup):
    choosing_branch = State()
    choosing_action = State()
    waiting_message_text = State()
    confirming_message = State()
    confirming_statistics = State()


class AdminRegulationStates(StatesGroup):
    waiting_text = State()


class AdminKpiStates(StatesGroup):
    waiting_rules = State()
