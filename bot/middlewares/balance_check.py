import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.keyboards.inline import no_credits_kb
from bot.utils import ensure_user
from database import Database

logger = logging.getLogger(__name__)

# Handler flag: {"requires_credit": True}
REQUIRES_CREDIT = {"requires_credit": True}

NO_CREDITS_TEXT = (
    "⚠️ <b>Sizda generatsiyalar soni tugadi!</b>\n\n"
    "Yangi slayd yoki referat yaratish uchun hisobingizni to'ldiring "
    "yoki do'stlaringizni taklif qilib bepul kredit oling."
)


class BalanceCheckMiddleware(BaseMiddleware):
    """Blocks handlers flagged with `requires_credit` when the user has no credits left.

    Must be registered as an inner middleware (router.message.middleware / router.callback_query.middleware)
    so that handler flags are already resolved. On success injects `balance: UserBalance` into the handler.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not get_flag(data, "requires_credit"):
            return await handler(event, data)

        tg_user = data.get("event_from_user")
        db: Database | None = data.get("db")
        if tg_user is None or db is None:
            return await handler(event, data)

        try:
            balance = await db.get_user_balance(tg_user.id)
            if balance is None:
                await ensure_user(db, tg_user)
                balance = await db.get_user_balance(tg_user.id)
        except Exception:
            logger.exception("Balance check failed for user %s", tg_user.id)
            await self._reply(event, "⚠️ Hisobingizni tekshirishda xatolik yuz berdi. Birozdan so'ng urinib ko'ring.")
            return None

        if balance is None or balance.total <= 0:
            await self._reply(event, NO_CREDITS_TEXT, with_keyboard=True)
            return None

        data["balance"] = balance
        return await handler(event, data)

    @staticmethod
    async def _reply(event: TelegramObject, text: str, with_keyboard: bool = False) -> None:
        markup = no_credits_kb() if with_keyboard else None
        try:
            if isinstance(event, CallbackQuery):
                await event.answer()
                if event.message is not None:
                    await event.message.answer(text, reply_markup=markup)
            elif isinstance(event, Message):
                await event.answer(text, reply_markup=markup)
        except TelegramAPIError:
            logger.warning("Could not deliver balance warning", exc_info=True)
