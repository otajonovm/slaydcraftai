from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_PRESENTATION = "📊 Slayd tayyorlash"
BTN_REFERAT = "📄 Referat tayyorlash"
BTN_BALANCE = "💳 Balans / Tariflar"
BTN_REFERRAL = "👥 Bepul kredit olish"
BTN_PROFILE = "👤 Profil"
BTN_HELP = "ℹ️ Yordam"
BTN_CANCEL = "❌ Bekor qilish"

MENU_TEXTS = frozenset(
    {BTN_PRESENTATION, BTN_REFERAT, BTN_BALANCE, BTN_REFERRAL, BTN_PROFILE, BTN_HELP, BTN_CANCEL}
)


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_PRESENTATION), KeyboardButton(text=BTN_REFERAT)],
            [KeyboardButton(text=BTN_BALANCE), KeyboardButton(text=BTN_REFERRAL)],
            [KeyboardButton(text=BTN_PROFILE), KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Kerakli bo'limni tanlang",
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )
