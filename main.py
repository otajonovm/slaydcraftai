import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

from bot.handlers import setup_routers
from config import settings
from database import Database, Transaction
from services.gemini_service import GeminiService
from services.payment_service import PaymentService
from services.pdf_converter import PdfConverter

logger = logging.getLogger("slidecraft")

BOT_COMMANDS = [
    BotCommand(command="start", description="Bosh menyu"),
    BotCommand(command="slide", description="Slayd tayyorlash"),
    BotCommand(command="referat", description="Referat / mustaqil ish tayyorlash"),
    BotCommand(command="balance", description="Balans va tariflar"),
    BotCommand(command="referral", description="Bepul kredit olish"),
    BotCommand(command="profile", description="Profil"),
    BotCommand(command="help", description="Yordam"),
    BotCommand(command="cancel", description="Bekor qilish"),
]
ADMIN_COMMANDS = BOT_COMMANDS + [
    BotCommand(command="stats", description="Statistika"),
    BotCommand(command="pending", description="Tasdiq kutayotgan cheklar"),
    BotCommand(command="give", description="Kredit berish: /give id soni [free]"),
    BotCommand(command="addbalance", description="Balans qo'shish: /addbalance id so'm"),
    BotCommand(command="user", description="Foydalanuvchi ma'lumoti: /user id"),
]


def setup_logging() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s: %(message)s",
        stream=sys.stdout,
    )
    for noisy in ("httpx", "google_genai", "aiogram.event"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()

    db = Database(settings.database_path)
    await db.connect()

    gemini = GeminiService(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        fallback_models=settings.gemini_fallback_models,
    )
    pdf = PdfConverter(settings.libreoffice_path)
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    async def notify_paid(tx: Transaction) -> None:
        try:
            await bot.send_message(tx.user_id, f"🎉 To'lov qabul qilindi! Hisobingizga +{tx.credits_added} kredit qo'shildi.")
        except TelegramAPIError:
            logger.warning("Cannot notify user %s about online payment", tx.user_id)

    payments = PaymentService(settings, db, on_paid=notify_paid)
    if not settings.admin_chat_id:
        logger.warning("ADMIN_CHAT_ID/ADMIN_IDS not set: payment receipts cannot be forwarded to admins")

    dp = Dispatcher(storage=MemoryStorage())
    dp["db"] = db
    dp["gemini"] = gemini
    dp["pdf"] = pdf
    dp["payments"] = payments
    dp.include_router(setup_routers())

    try:
        me = await bot.get_me()
        logger.info("Bot started: @%s (id=%s)", me.username, me.id)
        await bot.set_my_commands(BOT_COMMANDS)
        for admin_id in settings.admin_ids:
            try:
                await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
            except TelegramAPIError:
                logger.warning("Cannot set admin commands for %s (has the admin started the bot?)", admin_id)
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
