"""Online payment providers (Click, Payme).

Both providers are disabled until merchant credentials are set in .env (CLICK_ENABLED / PAYME_ENABLED).
The request/response contracts follow the official merchant APIs, so activating a provider only requires
exposing `ClickProvider.handle_prepare/handle_complete` and `PaymeProvider.handle_rpc` through an HTTP
server (e.g. aiohttp) and filling the credentials.
"""

import base64
import hashlib
import hmac
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

from config import Settings
from database import Database, Transaction

logger = logging.getLogger(__name__)

# Called after a transaction becomes completed, e.g. to notify the user in Telegram.
OnPaid = Callable[[Transaction], Awaitable[None]]


@dataclass
class WebhookResult:
    status_code: int
    body: dict[str, Any] = field(default_factory=dict)


class PaymentProvider(ABC):
    name: str

    def __init__(self, settings: Settings, db: Database, on_paid: OnPaid | None = None) -> None:
        self.settings = settings
        self.db = db
        self.on_paid = on_paid

    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @abstractmethod
    def checkout_url(self, tx: Transaction, return_url: str = "") -> str:
        """Payment page URL the user opens from Telegram."""

    async def _fulfill(self, tx_id: int) -> Transaction | None:
        tx = await self.db.complete_transaction(tx_id)
        if tx is not None and self.on_paid is not None:
            try:
                await self.on_paid(tx)
            except Exception:
                logger.exception("on_paid callback failed for tx=%s", tx_id)
        return tx


# --------------------------------------------------------------------- Click


class ClickProvider(PaymentProvider):
    """Click SHOP API: Prepare (action=0) and Complete (action=1) callbacks."""

    name = "click"

    ERR_OK = 0
    ERR_SIGN = -1
    ERR_AMOUNT = -2
    ERR_ACTION = -3
    ERR_ALREADY_PAID = -4
    ERR_NOT_FOUND = -5
    ERR_CANCELLED = -9

    @property
    def enabled(self) -> bool:
        s = self.settings
        return s.click_enabled and bool(s.click_service_id and s.click_merchant_id and s.click_secret_key)

    def checkout_url(self, tx: Transaction, return_url: str = "") -> str:
        params = {
            "service_id": self.settings.click_service_id,
            "merchant_id": self.settings.click_merchant_id,
            "amount": tx.amount,
            "transaction_param": tx.id,
        }
        if return_url:
            params["return_url"] = return_url
        return "https://my.click.uz/services/pay?" + urlencode(params)

    def _sign(self, data: dict[str, Any], with_prepare_id: bool) -> str:
        parts = [
            str(data.get("click_trans_id", "")),
            str(data.get("service_id", "")),
            self.settings.click_secret_key,
            str(data.get("merchant_trans_id", "")),
        ]
        if with_prepare_id:
            parts.append(str(data.get("merchant_prepare_id", "")))
        parts += [str(data.get("amount", "")), str(data.get("action", "")), str(data.get("sign_time", ""))]
        return hashlib.md5("".join(parts).encode()).hexdigest()

    async def _validate(self, data: dict[str, Any], with_prepare_id: bool) -> tuple[int, str, Transaction | None]:
        if not hmac.compare_digest(self._sign(data, with_prepare_id), str(data.get("sign_string", ""))):
            return self.ERR_SIGN, "SIGN CHECK FAILED", None
        try:
            tx = await self.db.get_transaction(int(data.get("merchant_trans_id", 0)))
        except (TypeError, ValueError):
            tx = None
        if tx is None:
            return self.ERR_NOT_FOUND, "Transaction not found", None
        try:
            amount = float(data.get("amount", 0))
        except (TypeError, ValueError):
            amount = -1
        if abs(amount - tx.amount) > 0.01:
            return self.ERR_AMOUNT, "Incorrect amount", tx
        if tx.status == "completed":
            return self.ERR_ALREADY_PAID, "Already paid", tx
        if tx.status == "cancelled":
            return self.ERR_CANCELLED, "Transaction cancelled", tx
        return self.ERR_OK, "Success", tx

    async def handle_prepare(self, data: dict[str, Any]) -> WebhookResult:
        if not self.enabled:
            return WebhookResult(503, {"error": self.ERR_ACTION, "error_note": "Provider disabled"})
        code, note, tx = await self._validate(data, with_prepare_id=False)
        if code == self.ERR_OK and tx is not None:
            await self.db.set_transaction_external_id(tx.id, self.name, str(data.get("click_trans_id")))
        return WebhookResult(200, {
            "click_trans_id": data.get("click_trans_id"),
            "merchant_trans_id": data.get("merchant_trans_id"),
            "merchant_prepare_id": tx.id if tx else None,
            "error": code,
            "error_note": note,
        })

    async def handle_complete(self, data: dict[str, Any]) -> WebhookResult:
        if not self.enabled:
            return WebhookResult(503, {"error": self.ERR_ACTION, "error_note": "Provider disabled"})
        code, note, tx = await self._validate(data, with_prepare_id=True)
        if code == self.ERR_OK and tx is not None:
            if int(data.get("error", 0)) < 0:
                await self.db.cancel_transaction(tx.id)
                code, note = self.ERR_CANCELLED, "Transaction cancelled"
            else:
                await self._fulfill(tx.id)
        return WebhookResult(200, {
            "click_trans_id": data.get("click_trans_id"),
            "merchant_trans_id": data.get("merchant_trans_id"),
            "merchant_confirm_id": tx.id if tx else None,
            "error": code,
            "error_note": note,
        })


# --------------------------------------------------------------------- Payme


class PaymeProvider(PaymentProvider):
    """Payme Merchant API (JSON-RPC 2.0). Amounts are in tiyin (1 so'm = 100 tiyin)."""

    name = "payme"

    ERR_AUTH = -32504
    ERR_METHOD = -32601
    ERR_AMOUNT = -31001
    ERR_NOT_FOUND = -31003
    ERR_CANNOT_PERFORM = -31008
    ERR_ACCOUNT = -31050

    @property
    def enabled(self) -> bool:
        return self.settings.payme_enabled and bool(self.settings.payme_merchant_id and self.settings.payme_secret_key)

    def checkout_url(self, tx: Transaction, return_url: str = "") -> str:
        params = f"m={self.settings.payme_merchant_id};ac.order_id={tx.id};a={tx.amount * 100}"
        if return_url:
            params += f";c={return_url}"
        return "https://checkout.paycom.uz/" + base64.b64encode(params.encode()).decode()

    def _authorized(self, authorization_header: str) -> bool:
        if not authorization_header.startswith("Basic "):
            return False
        try:
            login, _, password = base64.b64decode(authorization_header[6:]).decode().partition(":")
        except Exception:
            return False
        return login == "Paycom" and hmac.compare_digest(password, self.settings.payme_secret_key)

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> WebhookResult:
        return WebhookResult(200, {"id": request_id, "error": {"code": code, "message": {"uz": message, "ru": message, "en": message}}})

    async def _find_order(self, params: dict[str, Any]) -> Transaction | None:
        try:
            return await self.db.get_transaction(int(params.get("account", {}).get("order_id", 0)))
        except (TypeError, ValueError):
            return None

    async def handle_rpc(self, payload: dict[str, Any], authorization_header: str) -> WebhookResult:
        request_id = payload.get("id")
        if not self.enabled:
            return self._error(request_id, self.ERR_CANNOT_PERFORM, "Provider disabled")
        if not self._authorized(authorization_header):
            return self._error(request_id, self.ERR_AUTH, "Unauthorized")

        method = payload.get("method")
        params = payload.get("params") or {}

        if method == "CheckPerformTransaction":
            tx = await self._find_order(params)
            if tx is None or tx.status != "pending":
                return self._error(request_id, self.ERR_ACCOUNT, "Order not found")
            if int(params.get("amount", 0)) != tx.amount * 100:
                return self._error(request_id, self.ERR_AMOUNT, "Incorrect amount")
            return WebhookResult(200, {"id": request_id, "result": {"allow": True}})

        if method == "CreateTransaction":
            tx = await self._find_order(params)
            if tx is None or tx.status != "pending":
                return self._error(request_id, self.ERR_ACCOUNT, "Order not found")
            if int(params.get("amount", 0)) != tx.amount * 100:
                return self._error(request_id, self.ERR_AMOUNT, "Incorrect amount")
            if tx.external_id and tx.external_id != params.get("id"):
                return self._error(request_id, self.ERR_CANNOT_PERFORM, "Order is being paid")
            await self.db.set_transaction_external_id(tx.id, self.name, str(params.get("id")))
            return WebhookResult(200, {"id": request_id, "result": {
                "create_time": params.get("time"), "transaction": str(tx.id), "state": 1,
            }})

        if method == "PerformTransaction":
            tx = await self.db.get_transaction_by_external_id(self.name, str(params.get("id")))
            if tx is None:
                return self._error(request_id, self.ERR_NOT_FOUND, "Transaction not found")
            if tx.status == "pending":
                tx = await self._fulfill(tx.id) or tx
            if tx.status != "completed":
                return self._error(request_id, self.ERR_CANNOT_PERFORM, "Cannot perform")
            return WebhookResult(200, {"id": request_id, "result": {
                "transaction": str(tx.id), "perform_time": int(tx.updated_at.timestamp() * 1000), "state": 2,
            }})

        if method == "CancelTransaction":
            tx = await self.db.get_transaction_by_external_id(self.name, str(params.get("id")))
            if tx is None:
                return self._error(request_id, self.ERR_NOT_FOUND, "Transaction not found")
            if tx.status == "completed":
                # Credits may already be spent; refunds are handled manually by support.
                return self._error(request_id, self.ERR_CANNOT_PERFORM, "Cannot cancel completed transaction")
            await self.db.cancel_transaction(tx.id)
            return WebhookResult(200, {"id": request_id, "result": {
                "transaction": str(tx.id), "cancel_time": int(tx.updated_at.timestamp() * 1000), "state": -1,
            }})

        if method == "CheckTransaction":
            tx = await self.db.get_transaction_by_external_id(self.name, str(params.get("id")))
            if tx is None:
                return self._error(request_id, self.ERR_NOT_FOUND, "Transaction not found")
            state = {"pending": 1, "completed": 2, "cancelled": -1}.get(tx.status, 1)
            ts = int(tx.updated_at.timestamp() * 1000)
            return WebhookResult(200, {"id": request_id, "result": {
                "create_time": int(tx.created_at.timestamp() * 1000),
                "perform_time": ts if state == 2 else 0,
                "cancel_time": ts if state == -1 else 0,
                "transaction": str(tx.id),
                "state": state,
                "reason": None,
            }})

        if method == "GetStatement":
            return WebhookResult(200, {"id": request_id, "result": {"transactions": []}})

        return self._error(request_id, self.ERR_METHOD, "Method not found")


class PaymentService:
    def __init__(self, settings: Settings, db: Database, on_paid: OnPaid | None = None) -> None:
        self.click = ClickProvider(settings, db, on_paid)
        self.payme = PaymeProvider(settings, db, on_paid)

    @property
    def online_providers(self) -> list[PaymentProvider]:
        return [p for p in (self.click, self.payme) if p.enabled]
