import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from bot.keyboards.inline import referral_kb
from bot.keyboards.reply import BTN_REFERRAL
from bot.utils import ensure_user
from config import settings
from database import Database

logger = logging.getLogger(__name__)
router = Router(name="referral")


async def referral_link(bot: Bot, user_id: int) -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?start=ref_{user_id}"


async def _send_referral(message: Message, bot: Bot, db: Database, user) -> None:
    try:
        await ensure_user(db, user)
        count = await db.count_referrals(user.id)
        link = await referral_link(bot, user.id)
    except Exception:
        logger.exception("Referral info failed for %s", user.id)
        await message.answer("⚠️ Ma'lumotlarni yuklashda xatolik. Birozdan so'ng urinib ko'ring.")
        return

    bonus = settings.referral_bonus_credits
    await message.answer(
        "Do'stlaringizni taklif qiling va bepul slayd/referat oling! 🎁\n\n"
        f"Har bir taklif qilingan do'stingiz uchun sizga <b>+{bonus} ta bepul kredit</b> taqdim etiladi.\n\n"
        "Sizning taklif havolangiz:\n"
        f"<code>{link}</code>\n\n"
        f"Taklif qilingan do'stlar soni: <b>{count} ta</b>",
        reply_markup=referral_kb(link),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.message(Command("referral"))
@router.message(F.text == BTN_REFERRAL)
async def show_referral(message: Message, bot: Bot, db: Database) -> None:
    await _send_referral(message, bot, db, message.from_user)


@router.callback_query(F.data == "ref:open")
async def open_referral(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    await callback.answer()
    await _send_referral(callback.message, bot, db, callback.from_user)
