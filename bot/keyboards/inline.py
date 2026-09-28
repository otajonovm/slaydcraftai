from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services.pricing import PACKAGES, fmt_uzs

LANGUAGES = {"uz": "🇺🇿 O'zbekcha", "ru": "🇷🇺 Ruscha", "en": "🇬🇧 Inglizcha"}
SLIDE_COUNTS = (8, 10, 12, 15)
THEMES = {
    "minimal_white": "⚪ Minimal White",
    "modern_blue": "🔵 Modern Blue",
    "dark_tech": "⚫ Dark Tech",
}
WORK_TYPES = {"referat": "📄 Referat", "mustaqil": "📘 Mustaqil ish"}
INSTITUTION_TYPES = {"otm": "🎓 OTM (Universitet)", "college": "🏫 Kollej / Texnikum", "school": "🏠 Maktab"}
REFERAT_SIZES = {"short": "📃 Qisqa (~5-7 varaq)", "standard": "📚 Standart (~10-15 varaq)"}

CANCEL_CB = "cancel"


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _cancel_row() -> list[InlineKeyboardButton]:
    return [_btn("❌ Bekor qilish", CANCEL_CB)]


def slide_count_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"{n} ta slayd", f"p:count:{n}") for n in SLIDE_COUNTS[:2]],
            [_btn(f"{n} ta slayd", f"p:count:{n}") for n in SLIDE_COUNTS[2:]],
            _cancel_row(),
        ]
    )


def language_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(text, f"{prefix}:lang:{code}")] for code, text in LANGUAGES.items()
        ] + [_cancel_row()]
    )


def theme_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn(text, f"p:theme:{key}")] for key, text in THEMES.items()] + [_cancel_row()]
    )


def work_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn(text, f"r:work:{key}") for key, text in WORK_TYPES.items()], _cancel_row()]
    )


def institution_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn(text, f"r:inst:{key}")] for key, text in INSTITUTION_TYPES.items()] + [_cancel_row()]
    )


def skip_kb(field: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn("⏭ O'tkazib yuborish", f"r:skip:{field}")], _cancel_row()]
    )


def city_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("📍 Toshkent", "r:city:Toshkent"), _btn("📍 Samarqand", "r:city:Samarqand")],
            [_btn("📍 Buxoro", "r:city:Buxoro"), _btn("📍 Andijon", "r:city:Andijon")],
            [_btn("📍 Farg'ona", "r:city:Farg'ona"), _btn("📍 Namangan", "r:city:Namangan")],
            _cancel_row(),
        ]
    )


def referat_size_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn(text, f"r:size:{key}")] for key, text in REFERAT_SIZES.items()] + [_cancel_row()]
    )


def no_credits_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn("💳 To'ldirish", "billing:open"), _btn("👥 Do'stni taklif qilish", "ref:open")]]
    )


def packages_kb() -> InlineKeyboardMarkup:
    rows = [
        [_btn(f"{p.emoji} {p.credits} ta — {fmt_uzs(p.price)} so'm", f"buy:pkg:{p.key}")]
        for p in PACKAGES.values()
    ]
    rows.append([_btn("👥 Bepul kredit olish", "ref:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_kb(tx_id: int, package_key: str, can_pay_from_balance: bool) -> InlineKeyboardMarkup:
    rows = []
    if can_pay_from_balance:
        rows.append([_btn("💰 Balansdan to'lash", f"buy:bal:{package_key}:{tx_id}")])
    rows.append([_btn("⬅️ Tariflar", "billing:open"), _btn("❌ Bekor qilish", f"buy:cancel:{tx_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_receipt_kb(tx_id: int, credits: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"✅ Tasdiqlash (+{credits} kredit)", f"adm:ok:{tx_id}")],
            [_btn("❌ Bekor qilish", f"adm:no:{tx_id}")],
        ]
    )


def referral_kb(link: str) -> InlineKeyboardMarkup:
    text = "SlideCraft AI — slayd va referatlarni bir necha soniyada tayyorlaydigan bot. Sinab ko'r 👇"
    share_url = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(text, safe='')}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Do'stlarga ulashish", url=share_url)],
            [_btn("💳 Tariflar", "billing:open")],
        ]
    )


def confirm_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("✅ Tayyorlashni boshlash", f"{prefix}:go")],
            [_btn("🔄 Qaytadan", f"{prefix}:restart"), _btn("❌ Bekor qilish", CANCEL_CB)],
        ]
    )
