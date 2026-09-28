import asyncio
import logging
import re
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message
from aiogram.types import User as TgUser

from bot.keyboards.inline import no_credits_kb
from bot.keyboards.reply import MENU_TEXTS, main_menu_kb
from config import settings
from database import Database, User

logger = logging.getLogger(__name__)

ACTIVE_JOBS: set[int] = set()
JOB_SEMAPHORE = asyncio.Semaphore(settings.max_concurrent_jobs)


class UserText(Filter):
    """Plain text that is not a menu button or a command."""

    async def __call__(self, message: Message) -> bool:
        text = (message.text or "").strip()
        return bool(text) and text not in MENU_TEXTS and not text.startswith("/")


class IsAdmin(Filter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return bool(event.from_user) and event.from_user.id in settings.admin_ids


async def ensure_user(db: Database, tg_user: TgUser) -> tuple[User, bool]:
    return await db.get_or_create_user(
        tg_user.id,
        tg_user.username,
        tg_user.full_name,
        tg_user.language_code,
        free_credits=settings.free_credits_on_start,
    )


async def safe_edit(message: Message | None, text: str, **kwargs) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            logger.debug("edit_text failed: %s", exc)


def safe_filename(text: str, max_len: int = 60) -> str:
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", text)
    name = re.sub(r"\s+", "_", name.strip())
    name = name.strip("._")[:max_len].rstrip("._")
    return name or "SlideCraft"


@asynccontextmanager
async def job_workspace() -> AsyncIterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="job_", dir=settings.temp_dir))
    try:
        yield path
    finally:
        await asyncio.to_thread(shutil.rmtree, path, True)


async def send_charge_report(
    bot: Bot, db: Database, chat_id: int, user_id: int, generation_id: int, is_free: bool
) -> None:
    """Spends one credit after a successful generation and tells the user what is left."""
    try:
        spent = await db.deduct_credit(user_id, use_free=is_free, generation_id=generation_id)
        balance = await db.get_user_balance(user_id)
    except Exception:
        logger.exception("Credit deduction failed for user=%s generation=%s", user_id, generation_id)
        spent, balance = None, None
    if spent is None:
        logger.warning("No credit could be deducted for user=%s generation=%s", user_id, generation_id)

    left = balance.total if balance else 0
    text = f"💳 1 kredit yechildi. Qolgan kreditlar: <b>{left} ta</b>"
    if spent == "free_credits":
        text += (
            "\n\nℹ️ Bu fayl bepul kredit bilan tayyorlandi, shuning uchun oxirgi sahifada SlideCraft AI belgisi bor. "
            "Pullik kredit bilan belgisiz fayl olasiz."
        )
    try:
        if left <= 0:
            await bot.send_message(
                chat_id,
                text + "\n\n⚠️ Kreditlaringiz tugadi. Hisobni to'ldiring yoki do'stlaringizni taklif qiling:",
                reply_markup=no_credits_kb(),
            )
            await bot.send_message(chat_id, "Bosh menyu 👇", reply_markup=main_menu_kb())
        else:
            await bot.send_message(chat_id, text + "\n\nYana biror narsa tayyorlaymizmi? 👇", reply_markup=main_menu_kb())
    except TelegramAPIError:
        logger.warning("Cannot send charge report to %s", chat_id)


def support_line() -> str:
    return f"\n\n💬 Savollar bo'yicha: @{settings.support_username}" if settings.support_username else ""
