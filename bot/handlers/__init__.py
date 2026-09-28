from aiogram import Router

from bot.handlers import admin, billing, common, presentation, referat, referral
from bot.middlewares import BalanceCheckMiddleware


def setup_routers() -> Router:
    balance_check = BalanceCheckMiddleware()
    for guarded in (presentation.router, referat.router):
        guarded.message.middleware(balance_check)
        guarded.callback_query.middleware(balance_check)

    root = Router(name="root")
    root.include_routers(
        common.router,
        admin.router,
        billing.router,
        referral.router,
        presentation.router,
        referat.router,
        common.fallback_router,
    )
    return root
