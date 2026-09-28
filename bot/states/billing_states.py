from aiogram.fsm.state import State, StatesGroup


class BillingStates(StatesGroup):
    waiting_receipt = State()
