from aiogram.fsm.state import State, StatesGroup


class PresentationStates(StatesGroup):
    topic = State()
    slide_count = State()
    language = State()
    theme = State()
    confirm = State()
