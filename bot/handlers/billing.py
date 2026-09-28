import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import admin_receipt_kb, packages_kb, payment_kb
from bot.keyboards.reply import BTN_BALANCE, cancel_kb, main_menu_kb
from bot.states import BillingStates
from bot.utils import UserText, ensure_user, safe_edit, support_line
from config import settings
from database import Database, Transaction, UserBalance
from services.pricing import PACKAGES, Package, fmt_uzs, get_package

logger = logging.getLogger(__name__)
router = Router(name="billing")

MAX_RECEIPT_BYTES = 20 * 1024 * 1024
RECEIPT_MIME_PREFIXES = ("image/", "application/pdf")


def tariffs_text(balance: UserBalance) -> str:
    lines = []
    for p in PACKAGES.values():
        note = f" ({p.note})" if p.note else ""
        lines.append(f"{p.emoji} {p.title} ({p.credits} ta) — <b>{fmt_uzs(p.price)} so'm</b>{note}")
    return (
        "💳 <b>Sizning hisobingiz:</b>\n"
        f"• Mavjud kreditlar: <b>{balance.total} ta</b> generatsiya"
        + (f" (shundan {balance.free_credits} ta bepul)" if balance.free_credits else "")
        + "\n"
        f"• Balans: <b>{fmt_uzs(balance.balance_uzs)} so'm</b>\n\n"
        "💰 <b>Xizmat tariflari:</b>\n"
        + "\n".join(lines)
        + "\n\nℹ️ Pullik kreditlar bilan tayyorlangan fayllarda SlideCraft AI belgisi bo'lmaydi.\n\n"
        "Hisobni to'ldirish uchun to'plamni tanlang:"
    )


def requisites_text(package: Package, tx: Transaction, balance: UserBalance) -> str:
    text = (
        f"🧾 <b>Buyurtma #{tx.id}</b>\n"
        f"📦 {package.emoji} {package.title} — <b>{package.credits} ta generatsiya</b>\n\n"
        f"💳 To'lov usuli: <code>{escape(settings.payment_card_number)}</code>\n"
        f"👤 Karta egasi: <b>{escape(settings.payment_card_holder)}</b>\n"
        f"💰 To'lov summasi: <b>{fmt_uzs(package.price)} so'm</b>\n\n"
        "📸 Iltimos, to'lovni amalga oshirgach, <b>chek skrinshotini</b> shu yerga yuboring.\n"
        "Admin tekshirgandan so'ng kreditlar avtomatik hisobingizga qo'shiladi."
    )
    if balance.balance_uzs >= package.price:
        text += f"\n\n💰 Balansingizda {fmt_uzs(balance.balance_uzs)} so'm bor — balansdan ham to'lashingiz mumkin."
    return text


async def _load_balance(db: Database, tg_user) -> UserBalance:
    await ensure_user(db, tg_user)
    balance = await db.get_user_balance(tg_user.id)
    if balance is None:
        raise RuntimeError(f"user {tg_user.id} not found after ensure_user")
    return balance


# ------------------------------------------------------------------ tariffs


@router.message(Command("balance"))
@router.message(F.text == BTN_BALANCE)
async def show_balance(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    try:
        balance = await _load_balance(db, message.from_user)
    except Exception:
        logger.exception("Balance view failed for %s", message.from_user.id)
        await message.answer("⚠️ Hisobni yuklashda xatolik. Birozdan so'ng urinib ko'ring.")
        return
    await message.answer(tariffs_text(balance), reply_markup=packages_kb())


@router.callback_query(F.data == "billing:open")
async def open_billing(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await callback.answer()
    data = await state.get_data()
    if await state.get_state() == BillingStates.waiting_receipt.state and data.get("tx_id"):
        try:
            await db.cancel_unpaid_transactions(callback.from_user.id)
        except Exception:
            logger.exception("Failed to cancel unpaid transactions")
        await state.clear()
    try:
        balance = await _load_balance(db, callback.from_user)
    except Exception:
        logger.exception("Balance view failed for %s", callback.from_user.id)
        await callback.message.answer("⚠️ Hisobni yuklashda xatolik. Birozdan so'ng urinib ko'ring.")
        return
    await callback.message.answer(tariffs_text(balance), reply_markup=packages_kb())


# ------------------------------------------------------------------ purchase


async def _create_manual_order(
    db: Database, tg_user, package: Package, state: FSMContext
) -> tuple[Transaction, UserBalance]:
    balance = await _load_balance(db, tg_user)
    await db.cancel_unpaid_transactions(tg_user.id)
    tx = await db.create_transaction(tg_user.id, package.key, package.price, package.credits, provider="manual")
    await state.set_state(BillingStates.waiting_receipt)
    await state.update_data(tx_id=tx.id)
    return tx, balance


async def start_purchase(message: Message, state: FSMContext, db: Database, package: Package) -> None:
    """Shows card requisites for a package; used by the Mini App deep link `/start buy_<package>`."""
    try:
        tx, balance = await _create_manual_order(db, message.from_user, package, state)
    except Exception:
        logger.exception("Failed to create transaction for %s", message.from_user.id)
        await message.answer("⚠️ Xatolik yuz berdi, qayta urinib ko'ring.", reply_markup=main_menu_kb())
        return
    await message.answer(
        requisites_text(package, tx, balance),
        reply_markup=payment_kb(tx.id, package.key, balance.balance_uzs >= package.price),
    )
    await message.answer("📸 Chek skrinshotini yuboring yoki bekor qiling:", reply_markup=cancel_kb())


@router.callback_query(F.data.startswith("buy:pkg:"))
async def choose_package(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    package = get_package(callback.data.rsplit(":", 1)[1])
    if package is None:
        await callback.answer("Bunday tarif mavjud emas", show_alert=True)
        return
    try:
        tx, balance = await _create_manual_order(db, callback.from_user, package, state)
    except Exception:
        logger.exception("Failed to create transaction for %s", callback.from_user.id)
        await callback.answer("⚠️ Xatolik yuz berdi, qayta urinib ko'ring.", show_alert=True)
        return

    await callback.answer()
    await safe_edit(
        callback.message,
        requisites_text(package, tx, balance),
        reply_markup=payment_kb(tx.id, package.key, balance.balance_uzs >= package.price),
    )
    await callback.message.answer("📸 Chek skrinshotini yuboring yoki bekor qiling:", reply_markup=cancel_kb())


@router.callback_query(F.data.startswith("buy:bal:"))
async def pay_from_balance(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    try:
        _, _, package_key, tx_id_raw = callback.data.split(":", 3)
        tx_id = int(tx_id_raw)
    except ValueError:
        await callback.answer("Noto'g'ri so'rov", show_alert=True)
        return
    package = get_package(package_key)
    if package is None:
        await callback.answer("Bunday tarif mavjud emas", show_alert=True)
        return

    user_id = callback.from_user.id
    try:
        tx = await db.pay_from_balance(user_id, package.key, package.price, package.credits)
        if tx is None:
            await callback.answer("Balansingizda mablag' yetarli emas.", show_alert=True)
            return
        await db.cancel_transaction(tx_id)
        balance = await db.get_user_balance(user_id)
    except Exception:
        logger.exception("Balance payment failed for %s", user_id)
        await callback.answer("⚠️ Xatolik yuz berdi, qayta urinib ko'ring.", show_alert=True)
        return

    await state.clear()
    await callback.answer("To'lov amalga oshirildi ✅")
    await safe_edit(
        callback.message,
        f"✅ <b>{package.title}</b> balansdan sotib olindi!\n"
        f"➕ {package.credits} ta kredit qo'shildi.\n"
        f"💳 Mavjud kreditlar: <b>{balance.total if balance else '—'} ta</b>",
    )
    await callback.message.answer("Endi slayd yoki referat tayyorlashingiz mumkin 👇", reply_markup=main_menu_kb())


@router.callback_query(F.data.startswith("buy:cancel:"))
async def cancel_purchase(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    try:
        tx_id = int(callback.data.rsplit(":", 1)[1])
        tx = await db.get_transaction(tx_id)
        if tx is not None and tx.user_id == callback.from_user.id and tx.receipt_image is None:
            await db.cancel_transaction(tx_id)
    except Exception:
        logger.exception("Cancel purchase failed")
    await state.clear()
    await callback.answer("Bekor qilindi")
    await safe_edit(callback.message, "❌ To'lov bekor qilindi.")
    await callback.message.answer("Bosh menyu 👇", reply_markup=main_menu_kb())


# ------------------------------------------------------------------ receipt


@router.message(BillingStates.waiting_receipt, F.photo | F.document)
async def got_receipt(message: Message, state: FSMContext, bot: Bot, db: Database) -> None:
    data = await state.get_data()
    tx_id = data.get("tx_id")
    tx = await db.get_transaction(tx_id) if tx_id else None
    if tx is None or tx.status != "pending" or tx.user_id != message.from_user.id:
        await state.clear()
        await message.answer("Bu buyurtma eskirgan. Iltimos, tarifni qaytadan tanlang.", reply_markup=main_menu_kb())
        return

    if message.photo:
        file_id = message.photo[-1].file_id
        is_photo = True
    else:
        doc = message.document
        mime = doc.mime_type or ""
        if not mime.startswith(RECEIPT_MIME_PREFIXES):
            await message.answer("Iltimos, chekni rasm (skrinshot) yoki PDF ko'rinishida yuboring.")
            return
        if doc.file_size and doc.file_size > MAX_RECEIPT_BYTES:
            await message.answer("Fayl juda katta (maksimum 20 MB). Iltimos, skrinshot yuboring.")
            return
        file_id = doc.file_id
        is_photo = False

    if not settings.admin_chat_id:
        logger.error("ADMIN_CHAT_ID is not configured, cannot forward receipt for tx=%s", tx.id)
        await message.answer(
            "⚠️ To'lovlarni qabul qilish vaqtincha sozlanmagan. Iltimos, keyinroq urinib ko'ring." + support_line()
        )
        return

    package = get_package(tx.package)
    tg = message.from_user
    username = f"@{tg.username}" if tg.username else "—"
    caption = (
        f"🧾 <b>Yangi to'lov #{tx.id}</b>\n\n"
        f"👤 {escape(tg.full_name)} ({escape(username)})\n"
        f"🆔 <code>{tg.id}</code>\n"
        f"📦 {escape(package.title if package else tx.package)} — <b>{tx.credits_added} kredit</b>\n"
        f"💰 Summa: <b>{fmt_uzs(tx.amount)} so'm</b>"
    )
    markup = admin_receipt_kb(tx.id, tx.credits_added)
    try:
        if is_photo:
            await bot.send_photo(settings.admin_chat_id, file_id, caption=caption, reply_markup=markup)
        else:
            await bot.send_document(settings.admin_chat_id, file_id, caption=caption, reply_markup=markup)
    except TelegramAPIError:
        logger.exception("Failed to forward receipt tx=%s to admin chat %s", tx.id, settings.admin_chat_id)
        await message.answer("⚠️ Chekni yuborishda xatolik yuz berdi. Iltimos, qayta yuboring." + support_line())
        return

    try:
        await db.attach_receipt(tx.id, file_id)
    except Exception:
        logger.exception("Failed to save receipt for tx=%s", tx.id)

    await state.clear()
    await message.answer(
        f"✅ Chek qabul qilindi! (buyurtma #{tx.id})\n\n"
        "⏳ Admin tekshiruvidan so'ng kreditlar hisobingizga qo'shiladi — odatda 5–30 daqiqa. "
        "Tasdiqlangach sizga xabar keladi." + support_line(),
        reply_markup=main_menu_kb(),
    )


@router.message(BillingStates.waiting_receipt, UserText())
async def waiting_receipt_text(message: Message) -> None:
    await message.answer(
        "📸 Iltimos, to'lov chekining <b>skrinshotini</b> (rasm) yuboring.\n"
        "Bekor qilish uchun «❌ Bekor qilish» tugmasini bosing."
    )
