import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import CANCEL_CB
from bot.keyboards.reply import BTN_CANCEL, BTN_HELP, BTN_PROFILE, main_menu_kb
from bot.states import BillingStates
from bot.utils import ACTIVE_JOBS, ensure_user, safe_edit, support_line
from config import settings
from database import Database
from services.pricing import PACKAGES, fmt_uzs

logger = logging.getLogger(__name__)

router = Router(name="common")
fallback_router = Router(name="fallback")


def _help_text() -> str:
    prices = "\n".join(f"{p.emoji} {p.title} — {fmt_uzs(p.price)} so'm" for p in PACKAGES.values())
    return (
        "<b>SlideCraft AI</b> — sun'iy intellekt yordamida taqdimot va referatlar tayyorlovchi bot.\n\n"
        "<b>📊 Slayd tayyorlash</b>\n"
        "Mavzu, slaydlar soni, til va dizaynni tanlaysiz — bot zamonaviy 16:9 formatdagi "
        "<b>.pptx</b> va <b>.pdf</b> fayllarni tayyorlab beradi.\n\n"
        "<b>📄 Referat tayyorlash</b>\n"
        "OTM standartlari bo'yicha titul, reja, kirish, 2 bob, xulosa va adabiyotlar ro'yxatidan iborat "
        "<b>.docx</b> va <b>.pdf</b>.\n\n"
        "<b>💳 Narxlar</b> (1 ta hujjat = 1 kredit)\n"
        f"{prices}\n\n"
        "🎁 Yangi foydalanuvchilarga 1 ta bepul sinov krediti beriladi. Bepul kreditlar bilan tayyorlangan "
        "fayllarning oxirgi sahifasida SlideCraft AI belgisi bo'ladi, pullik kreditlarda belgi yo'q.\n\n"
        "<b>Buyruqlar:</b>\n"
        "/start — bosh menyu\n"
        "/slide — taqdimot tayyorlash\n"
        "/referat — referat tayyorlash\n"
        "/balance — balans va tariflar\n"
        "/referral — bepul kredit olish\n"
        "/profile — profil\n"
        "/cancel — joriy amalni bekor qilish"
        f"{support_line()}"
    )


def _parse_referrer(command: CommandObject | None) -> int | None:
    args = (command.args or "").strip() if command else ""
    if args.startswith("ref_") and args[4:].isdigit():
        return int(args[4:])
    return None


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: CommandObject, bot: Bot, db: Database) -> None:
    await state.clear()
    tg = message.from_user
    try:
        user, created = await ensure_user(db, tg)
    except Exception:
        logger.exception("Failed to register user %s", tg.id)
        await message.answer("⚠️ Texnik xatolik yuz berdi. Iltimos, birozdan so'ng /start bosing.")
        return

    referrer_id = _parse_referrer(command)
    if created and referrer_id and referrer_id != tg.id:
        try:
            rewarded = await db.add_referral(tg.id, referrer_id, settings.referral_bonus_credits)
        except Exception:
            logger.exception("Referral processing failed: %s -> %s", referrer_id, tg.id)
            rewarded = False
        if rewarded:
            try:
                await bot.send_message(
                    referrer_id,
                    f"🎉 Do'stingiz botga qo'shildi! Sizga +{settings.referral_bonus_credits} bepul generatsiya berildi.",
                )
            except TelegramAPIError:
                logger.info("Cannot notify referrer %s", referrer_id)

    name = escape(tg.first_name or "do'st")
    if created and settings.free_credits_on_start > 0:
        gift = f"🎁 Sizga {settings.free_credits_on_start} ta <b>BEPUL</b> sinov imkoniyati taqdim etildi!\n\n"
    else:
        gift = f"💳 Mavjud kreditlaringiz: <b>{user.total_credits} ta</b>\n\n"

    await message.answer(
        f"Assalomu alaykum, <b>{name}</b>! 👋\n\n"
        "<b>SlideCraft AI</b> — professional slaydlar va referatlarni bir necha soniyada tayyorlab beruvchi bot.\n\n"
        f"{gift}"
        "Quyidagi bo'limlardan birini tanlang:",
        reply_markup=main_menu_kb(),
    )


@router.message(Command("help"))
@router.message(F.text == BTN_HELP)
async def cmd_help(message: Message) -> None:
    await message.answer(_help_text(), reply_markup=main_menu_kb())


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def cmd_cancel(message: Message, state: FSMContext, db: Database) -> None:
    if await state.get_state() == BillingStates.waiting_receipt.state:
        try:
            await db.cancel_unpaid_transactions(message.from_user.id)
        except Exception:
            logger.exception("Failed to cancel unpaid transactions for %s", message.from_user.id)
    await state.clear()
    text = "❌ Amal bekor qilindi."
    if message.from_user.id in ACTIVE_JOBS:
        text += "\n⏳ Joriy generatsiya fonda davom etmoqda, tayyor bo'lgach yuboriladi."
    await message.answer(text, reply_markup=main_menu_kb())


@router.callback_query(F.data == CANCEL_CB)
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Bekor qilindi")
    await safe_edit(callback.message, "❌ Amal bekor qilindi.")
    await callback.message.answer("Bosh menyu 👇", reply_markup=main_menu_kb())


@router.message(Command("profile"))
@router.message(F.text == BTN_PROFILE)
async def cmd_profile(message: Message, db: Database) -> None:
    tg = message.from_user
    try:
        user, _ = await ensure_user(db, tg)
        stats = await db.get_user_stats(tg.id)
        referrals = await db.count_referrals(tg.id)
        recent = await db.get_recent_generations(tg.id)
    except Exception:
        logger.exception("Profile failed for %s", tg.id)
        await message.answer("⚠️ Profilni yuklashda xatolik. Birozdan so'ng urinib ko'ring.")
        return

    recent_text = ""
    if recent:
        icons = {"presentation": "📊", "referat": "📄"}
        lines = [f"{icons.get(g.gen_type, '•')} {escape(g.topic[:60])}" for g in recent]
        recent_text = "\n\n<b>So'nggi ishlar:</b>\n" + "\n".join(lines)

    status = "💎 Premium" if user.is_premium else "🆓 Bepul"
    await message.answer(
        "👤 <b>Profil</b>\n\n"
        f"🆔 ID: <code>{tg.id}</code>\n"
        f"👤 Ism: {escape(tg.full_name)}\n"
        f"⭐ Status: {status}\n\n"
        f"💳 Pullik kreditlar: <b>{user.credits} ta</b>\n"
        f"🎁 Bepul kreditlar: <b>{user.free_credits} ta</b>\n"
        f"💰 Balans: <b>{fmt_uzs(user.balance_uzs)} so'm</b>\n"
        f"👥 Taklif qilingan do'stlar: <b>{referrals} ta</b>\n\n"
        f"📊 Taqdimotlar: <b>{stats['presentations']}</b>\n"
        f"📄 Referatlar: <b>{stats['referats']}</b>\n"
        f"📦 Jami: <b>{stats['total']}</b>"
        f"{recent_text}",
        reply_markup=main_menu_kb(),
    )


@fallback_router.callback_query()
async def stale_callback(callback: CallbackQuery) -> None:
    await callback.answer("Bu tugma eskirgan. Iltimos, menyudan qaytadan boshlang.", show_alert=True)


@fallback_router.message()
async def unknown_message(message: Message, state: FSMContext) -> None:
    if await state.get_state() is not None:
        await message.answer("Iltimos, yuqoridagi tugmalardan birini tanlang yoki /cancel bosing.")
        return
    await message.answer(
        "Men slayd va referat tayyorlayman. Quyidagi menyudan bo'limni tanlang 👇",
        reply_markup=main_menu_kb(),
    )
