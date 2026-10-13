from aiogram.fsm.state import State, StatesGroup


class TopUpStates(StatesGroup):
    waiting_amount = State()


class BuyStates(StatesGroup):
    waiting_entry_data = State()
    waiting_phone = State()
    waiting_code = State()
    waiting_email = State()
    waiting_email_pass = State()


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


class SellerAddAccount(StatesGroup):
    country = State()
    age = State()
    phone = State()
    method = State()          # session | phone_code
    session = State()
    code = State()
    password_2fa = State()


class OwnerAddManual(StatesGroup):
    name = State()
    price = State()
    content = State()


class OwnerAddTgOffer(StatesGroup):
    country = State()
    age = State()
    buyer_price = State()
    seller_price = State()
