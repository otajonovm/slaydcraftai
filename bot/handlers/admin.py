import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import admin_receipt_kb
from bot.keyboards.reply import main_menu_kb
from bot.utils import ACTIVE_JOBS, IsAdmin, support_line
from config import settings
from database import Database
from services.pricing import fmt_uzs, get_package

logger = logging.getLogger(__name__)
router = Router(name="admin")

STATUS_LABELS = {"completed": "✅ tasdiqlangan", "cancelled": "❌ bekor qilingan", "pending": "⏳ kutilmoqda"}


def _can_moderate(callback: CallbackQuery) -> bool:
    if callback.from_user.id in settings.admin_ids:
        return True
    # Without explicit ADMIN_IDS anyone inside the configured admin chat may moderate.
    return (
        not settings.admin_ids
        and callback.message is not None
        and settings.admin_chat_id is not None
        and callback.message.chat.id == settings.admin_chat_id
    )


async def _mark_processed(callback: CallbackQuery, status_line: str) -> None:
    message = callback.message
    if message is None:
        return
    base = message.html_text or ""
    try:
        if message.caption is not None:
            await message.edit_caption(caption=f"{base}\n\n{status_line}", reply_markup=None)
        else:
            await message.edit_text(f"{base}\n\n{status_line}", reply_markup=None)
    except TelegramBadRequest as exc:
        logger.debug("Cannot edit admin message: %s", exc)


def _admin_name(callback: CallbackQuery) -> str:
    user = callback.from_user
    return escape(f"@{user.username}" if user.username else user.full_name)


def _parse_tx_id(data: str) -> int | None:
    try:
        return int(data.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


# --------------------------------------------------------------- receipts


@router.callback_query(F.data.startswith("adm:ok:"))
async def approve_payment(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    if not _can_moderate(callback):
        await callback.answer("⛔ Sizda ruxsat yo'q", show_alert=True)
        return
    tx_id = _parse_tx_id(callback.data)
    if tx_id is None:
        await callback.answer("Noto'g'ri so'rov", show_alert=True)
        return

    try:
        tx = await db.complete_transaction(tx_id, admin_id=callback.from_user.id)
        if tx is None:
            existing = await db.get_transaction(tx_id)
            status = STATUS_LABELS.get(existing.status, existing.status) if existing else "topilmadi"
            await callback.answer(f"Bu to'lov allaqachon {status}", show_alert=True)
            await _mark_processed(callback, f"ℹ️ Holat: {status}")
            return
        balance = await db.get_user_balance(tx.user_id)
    except Exception:
        logger.exception("Approve failed for tx=%s", tx_id)
        await callback.answer("⚠️ Xatolik yuz berdi, qayta urinib ko'ring", show_alert=True)
        return

    logger.info("Transaction %s approved by %s (+%s credits to %s)", tx.id, callback.from_user.id,
                tx.credits_added, tx.user_id)
    await _mark_processed(callback, f"✅ <b>Tasdiqlandi</b> — {_admin_name(callback)}")
    await callback.answer("Tasdiqlandi ✅")

    package = get_package(tx.package)
    try:
        await bot.send_message(
            tx.user_id,
            "🎉 <b>To'lovingiz tasdiqlandi!</b>\n\n"
            f"📦 {escape(package.title if package else tx.package)}\n"
            f"➕ Hisobingizga <b>{tx.credits_added} ta kredit</b> qo'shildi.\n"
            f"💳 Mavjud kreditlar: <b>{balance.total if balance else tx.credits_added} ta</b>\n\n"
            "Rahmat! Endi belgisiz (watermark'siz) slayd va referatlar tayyorlashingiz mumkin 👇",
            reply_markup=main_menu_kb(),
        )
    except TelegramAPIError:
        logger.warning("Cannot notify user %s about approved tx=%s", tx.user_id, tx.id)


@router.callback_query(F.data.startswith("adm:no:"))
async def reject_payment(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    if not _can_moderate(callback):
        await callback.answer("⛔ Sizda ruxsat yo'q", show_alert=True)
        return
    tx_id = _parse_tx_id(callback.data)
    if tx_id is None:
        await callback.answer("Noto'g'ri so'rov", show_alert=True)
        return

    try:
        tx = await db.cancel_transaction(tx_id, admin_id=callback.from_user.id)
        if tx is None:
            existing = await db.get_transaction(tx_id)
            status = STATUS_LABELS.get(existing.status, existing.status) if existing else "topilmadi"
            await callback.answer(f"Bu to'lov allaqachon {status}", show_alert=True)
            await _mark_processed(callback, f"ℹ️ Holat: {status}")
            return
    except Exception:
        logger.exception("Reject failed for tx=%s", tx_id)
        await callback.answer("⚠️ Xatolik yuz berdi, qayta urinib ko'ring", show_alert=True)
        return

    logger.info("Transaction %s rejected by %s", tx.id, callback.from_user.id)
    await _mark_processed(callback, f"❌ <b>Bekor qilindi</b> — {_admin_name(callback)}")
    await callback.answer("Bekor qilindi")
    try:
        await bot.send_message(
            tx.user_id,
            f"❌ <b>To'lovingiz tasdiqlanmadi</b> (buyurtma #{tx.id}).\n\n"
            "Chek noto'g'ri yoki to'lov topilmadi. Agar to'lov qilgan bo'lsangiz, "
            "chekni qaytadan yuboring yoki qo'llab-quvvatlash xizmatiga yozing." + support_line(),
            reply_markup=main_menu_kb(),
        )
    except TelegramAPIError:
        logger.warning("Cannot notify user %s about rejected tx=%s", tx.user_id, tx.id)


# --------------------------------------------------------------- commands


@router.message(Command("stats"), IsAdmin())
async def cmd_stats(message: Message, db: Database) -> None:
    try:
        s = await db.get_global_stats()
    except Exception:
        logger.exception("Stats failed")
        await message.answer("⚠️ Statistikani olishda xatolik.")
        return
    await message.answer(
        "📈 <b>Bot statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{s['users']}</b> (bugun +{s['users_today']})\n"
        f"💎 Premium: <b>{s['premium']}</b>\n"
        f"🤝 Referal orqali kelganlar: <b>{s['referred']}</b>\n\n"
        f"📦 Generatsiyalar: <b>{s['total']}</b> (bugun {s['today']})\n"
        f"📊 Taqdimotlar: <b>{s['presentations']}</b>\n"
        f"📄 Referatlar: <b>{s['referats']}</b>\n"
        f"⚠️ Xatoliklar: <b>{s['failed']}</b>\n"
        f"⏳ Hozir jarayonda: <b>{len(ACTIVE_JOBS)}</b>\n\n"
        f"💰 Daromad: <b>{fmt_uzs(s['revenue'])} so'm</b> (bugun {fmt_uzs(s['revenue_today'])} so'm)\n"
        f"🧾 Tasdiq kutayotgan cheklar: <b>{s['pending']}</b>"
    )


@router.message(Command("pending"), IsAdmin())
async def cmd_pending(message: Message, bot: Bot, db: Database) -> None:
    try:
        pending = await db.list_pending_transactions(limit=10)
    except Exception:
        logger.exception("Pending list failed")
        await message.answer("⚠️ Ro'yxatni olishda xatolik.")
        return
    if not pending:
        await message.answer("✅ Tasdiq kutayotgan to'lovlar yo'q.")
        return
    for tx in pending:
        caption = (
            f"🧾 <b>To'lov #{tx.id}</b> (kutilmoqda)\n"
            f"🆔 <code>{tx.user_id}</code>\n"
            f"📦 {escape(tx.package)} — <b>{tx.credits_added} kredit</b>\n"
            f"💰 {fmt_uzs(tx.amount)} so'm • {tx.created_at:%d.%m.%Y %H:%M} UTC"
        )
        markup = admin_receipt_kb(tx.id, tx.credits_added)
        try:
            await bot.send_photo(message.chat.id, tx.receipt_image, caption=caption, reply_markup=markup)
        except TelegramBadRequest:
            try:
                await bot.send_document(message.chat.id, tx.receipt_image, caption=caption, reply_markup=markup)
            except TelegramAPIError:
                await message.answer(caption + "\n⚠️ Chek faylini ochib bo'lmadi", reply_markup=markup)


@router.message(Command("give"), IsAdmin())
async def cmd_give(message: Message, command: CommandObject, bot: Bot, db: Database) -> None:
    """/give <telegram_id> <credits> [free]"""
    args = (command.args or "").split()
    if len(args) < 2 or not args[0].isdigit() or not args[1].lstrip("-").isdigit():
        await message.answer("Foydalanish: <code>/give &lt;telegram_id&gt; &lt;kreditlar&gt; [free]</code>")
        return
    user_id, amount = int(args[0]), int(args[1])
    free = len(args) > 2 and args[2].lower() == "free"
    if amount <= 0:
        await message.answer("Kreditlar soni musbat bo'lishi kerak.")
        return
    try:
        ok = await db.add_credit(user_id, amount, free=free)
        balance = await db.get_user_balance(user_id) if ok else None
    except Exception:
        logger.exception("Give credits failed")
        await message.answer("⚠️ Xatolik yuz berdi.")
        return
    if not ok:
        await message.answer("Foydalanuvchi topilmadi (u avval botga /start bosishi kerak).")
        return
    kind = "bepul" if free else "pullik"
    await message.answer(f"✅ {user_id} ga +{amount} {kind} kredit qo'shildi. Jami: {balance.total} ta.")
    try:
        await bot.send_message(user_id, f"🎁 Hisobingizga <b>+{amount} ta kredit</b> qo'shildi!",
                               reply_markup=main_menu_kb())
    except TelegramAPIError:
        pass


@router.message(Command("addbalance"), IsAdmin())
async def cmd_add_balance(message: Message, command: CommandObject, db: Database) -> None:
    """/addbalance <telegram_id> <so'm>"""
    args = (command.args or "").split()
    if len(args) != 2 or not all(a.isdigit() for a in args):
        await message.answer("Foydalanish: <code>/addbalance &lt;telegram_id&gt; &lt;so'm&gt;</code>")
        return
    user_id, amount = int(args[0]), int(args[1])
    try:
        ok = amount > 0 and await db.add_balance(user_id, amount)
    except Exception:
        logger.exception("Add balance failed")
        await message.answer("⚠️ Xatolik yuz berdi.")
        return
    await message.answer(f"✅ {user_id} balansiga +{fmt_uzs(amount)} so'm qo'shildi." if ok else "Foydalanuvchi topilmadi.")


@router.message(Command("user"), IsAdmin())
async def cmd_user(message: Message, command: CommandObject, db: Database) -> None:
    """/user <telegram_id>"""
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Foydalanish: <code>/user &lt;telegram_id&gt;</code>")
        return
    try:
        user = await db.get_user(int(arg))
        if user is None:
            await message.answer("Foydalanuvchi topilmadi.")
            return
        stats = await db.get_user_stats(user.telegram_id)
        referrals = await db.count_referrals(user.telegram_id)
    except Exception:
        logger.exception("User info failed")
        await message.answer("⚠️ Xatolik yuz berdi.")
        return
    await message.answer(
        f"👤 <b>{escape(user.full_name or '—')}</b> (@{escape(user.username or '—')})\n"
        f"🆔 <code>{user.telegram_id}</code>\n"
        f"📅 Ro'yxatdan o'tgan: {user.created_at:%d.%m.%Y}\n"
        f"💳 Pullik: {user.credits} • 🎁 Bepul: {user.free_credits} • 💰 {fmt_uzs(user.balance_uzs)} so'm\n"
        f"⭐ Premium: {'ha' if user.is_premium else 'yo`q'}\n"
        f"🤝 Taklif qilgan: {user.referrer_id or '—'} • Do'stlari: {referrals}\n"
        f"📦 Generatsiyalar: {stats['total']} (📊 {stats['presentations']}, 📄 {stats['referats']})"
    )
