from aiogram.fsm.state import State, StatesGroup


class TopUpStates(StatesGroup):
    waiting_amount = State()


class BuyStates(StatesGroup):
    waiting_entry_data = State()  # ждём email/password или phone/code


class WithdrawStates(StatesGroup):
    waiting_amount = State()


class OwnerAddProduct(StatesGroup):
    name = State()
    buyer_price = State()
    seller_price = State()
    entry_type = State()


class OwnerEditProduct(StatesGroup):
    choose_field = State()
    new_value = State()


class OwnerAddSeller(StatesGroup):
    waiting_id = State()


class OwnerAddAdmin(StatesGroup):
    waiting_id = State()


class OwnerBroadcast(StatesGroup):
    waiting_message = State()


class OwnerSetLink(StatesGroup):
    waiting_value = State()
