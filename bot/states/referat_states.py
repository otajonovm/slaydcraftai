from aiogram.fsm.state import State, StatesGroup


class ReferatStates(StatesGroup):
    topic = State()
    work_type = State()
    institution_type = State()
    institution_name = State()
    student = State()
    teacher = State()
    city = State()
    size = State()
    language = State()
    confirm = State()
