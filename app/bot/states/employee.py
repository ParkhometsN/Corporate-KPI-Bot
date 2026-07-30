from aiogram.fsm.state import State, StatesGroup


class EmployeeConnectionStates(StatesGroup):
    waiting_code = State()

class EmployeeProductSearchStates(StatesGroup):
    waiting_query = State()

