"""HTTP API for the Telegram Mini App plus Click/Payme webhooks (aiohttp, runs next to polling)."""

import hashlib
import hmac
import io
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import quote

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile
from aiohttp import web

from api.auth import WebAppAuth, validate_init_data
from api.jobs import Job, JobManager, cache_path
from bot.utils import ACTIVE_JOBS
from config import settings
from database import Database, GeneratedFile, GenerationHistory, User
from services.payment_service import PaymentService
from services.pricing import PACKAGES, get_package

logger = logging.getLogger(__name__)

TOPIC_MIN, TOPIC_MAX = 3, 300
NAME_MAX = 120
LANGUAGES = {"uz", "ru", "en"}
SLIDE_COUNTS = {8, 10, 12, 15}
STYLE_THEMES = {"business": "modern_blue", "academic": "minimal_white", "creative": "dark_tech"}
REFERAT_SIZES = {"short", "standard"}
WORK_TYPES = {"referat", "mustaqil"}
INSTITUTION_TYPES = {"otm", "college", "school"}
DOWNLOAD_LINK_TTL = 6 * 3600
CONTENT_TYPES = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}
TARIFF_BADGES = {"student": "Ommabop", "session": "Tejamkor"}


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


# ------------------------------------------------------------------ helpers


def _iso(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _clean(value: Any, max_len: int) -> str:
    return " ".join(str(value or "").split())[:max_len]


def _download_secret() -> bytes:
    return hashlib.sha256(b"slidecraft-files:" + settings.bot_token.encode()).digest()


def _sign(file_id: str, exp: int) -> str:
    return hmac.new(_download_secret(), f"{file_id}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def _public_base(request: web.Request) -> str:
    proto = request.headers.get("X-Forwarded-Proto", request.scheme).split(",")[0].strip()
    return f"{proto}://{request.host}"


def _file_json(request: web.Request, f: GeneratedFile) -> dict[str, Any]:
    exp = int(time.time()) + DOWNLOAD_LINK_TTL
    url = f"{_public_base(request)}/api/files/{f.id}/download?exp={exp}&sig={_sign(f.id, exp)}"
    return {"id": f.id, "name": f.name, "format": f.file_format, "sizeBytes": f.size_bytes, "url": url}


def _job_json(request: web.Request, job: Job) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "files": [_file_json(request, f) for f in job.files],
        "error": job.error,
        "isFree": job.is_free,
    }


def _generation_status(gen: GenerationHistory) -> str:
    return {"success": "completed", "processing": "running"}.get(gen.status, "failed")


def _parse_job_request(body: dict[str, Any]) -> dict[str, Any]:
    doc_type = body.get("type")
    if doc_type not in ("presentation", "referat", "pdf"):
        raise ApiError(400, "Hujjat turi noto'g'ri")
    topic = _clean(body.get("topic"), TOPIC_MAX + 1)
    if not TOPIC_MIN <= len(topic) <= TOPIC_MAX:
        raise ApiError(400, f"Mavzu {TOPIC_MIN}–{TOPIC_MAX} belgi oralig'ida bo'lishi kerak")
    language = body.get("language", "uz")
    if language not in LANGUAGES:
        raise ApiError(400, "Til noto'g'ri tanlangan")

    req: dict[str, Any] = {"type": doc_type, "topic": topic, "language": language}
    source = doc_type if doc_type != "pdf" else body.get("source", "presentation")
    if source not in ("presentation", "referat"):
        raise ApiError(400, "PDF asosi noto'g'ri")
    if doc_type == "pdf":
        req["source"] = source

    if source == "presentation":
        slides = body.get("slides", 10)
        style = body.get("style", "business")
        if slides not in SLIDE_COUNTS:
            raise ApiError(400, "Slaydlar soni noto'g'ri")
        if style not in STYLE_THEMES:
            raise ApiError(400, "Uslub noto'g'ri")
        req.update(slides=slides, style=style, theme=STYLE_THEMES[style])
    else:
        size = body.get("size", "standard")
        work_type = body.get("workType", "referat")
        institution_type = body.get("institutionType", "otm")
        if size not in REFERAT_SIZES or work_type not in WORK_TYPES or institution_type not in INSTITUTION_TYPES:
            raise ApiError(400, "Referat parametrlari noto'g'ri")
        req.update(
            size=size,
            work_type=work_type,
            institution_type=institution_type,
            institution=_clean(body.get("institution"), 200),
            student=_clean(body.get("student"), NAME_MAX),
            teacher=_clean(body.get("teacher"), NAME_MAX),
            city=_clean(body.get("city"), 60) or "Toshkent",
        )
    return req


# ------------------------------------------------------------------ app


def create_app(bot: Bot, db: Database, jobs: JobManager, payments: PaymentService) -> web.Application:
    bot_username: dict[str, str] = {}

    async def get_bot_username() -> str:
        if "value" not in bot_username:
            bot_username["value"] = (await bot.me()).username or ""
        return bot_username["value"]

    # -------------------------------------------------------------- middlewares

    @web.middleware
    async def cors_middleware(
        request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
    ) -> web.StreamResponse:
        origin = request.headers.get("Origin", "")
        allowed = settings.api_cors_origins
        allow_origin = "*" if "*" in allowed else (origin if origin in allowed else "")
        if request.method == "OPTIONS":
            response: web.StreamResponse = web.Response(status=204)
        else:
            try:
                response = await handler(request)
            except ApiError as exc:
                response = web.json_response({"detail": exc.detail}, status=exc.status)
            except web.HTTPException as exc:
                response = web.json_response({"detail": exc.reason}, status=exc.status)
            except Exception:
                logger.exception("Unhandled API error on %s %s", request.method, request.path)
                response = web.json_response({"detail": "Serverda xatolik yuz berdi"}, status=500)
        if allow_origin:
            response.headers["Access-Control-Allow-Origin"] = allow_origin
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Max-Age"] = "86400"
            if allow_origin != "*":
                response.headers["Vary"] = "Origin"
        return response

    # -------------------------------------------------------------- auth

    async def authenticate(request: web.Request) -> tuple[WebAppAuth, User]:
        header = request.headers.get("Authorization", "")
        scheme, _, init_data = header.partition(" ")
        auth = validate_init_data(init_data.strip(), settings.bot_token) if scheme.lower() == "tma" else None
        if auth is None:
            raise ApiError(401, "Avtorizatsiya xatosi. Ilovani bot orqali qayta oching.")
        user, created = await db.get_or_create_user(
            auth.user_id, auth.username, auth.full_name or None, auth.language_code,
            free_credits=settings.free_credits_on_start,
        )
        if user.is_blocked:
            raise ApiError(403, "Hisobingiz bloklangan")
        if created and auth.start_param and auth.start_param.startswith("ref_") and auth.start_param[4:].isdigit():
            referrer_id = int(auth.start_param[4:])
            try:
                if await db.add_referral(auth.user_id, referrer_id, settings.referral_bonus_credits):
                    await bot.send_message(
                        referrer_id,
                        f"🎉 Do'stingiz botga qo'shildi! Sizga +{settings.referral_bonus_credits} bepul generatsiya berildi.",
                    )
            except TelegramAPIError:
                logger.info("Cannot notify referrer %s", referrer_id)
            except Exception:
                logger.exception("Referral processing failed: %s -> %s", referrer_id, auth.user_id)
        return auth, user

    # -------------------------------------------------------------- handlers

    async def index(_: web.Request) -> web.Response:
        return web.json_response({"service": "SlideCraft AI API", "ok": True})

    async def me(request: web.Request) -> web.Response:
        auth, user = await authenticate(request)
        username = await get_bot_username()
        referrals = await db.count_referrals(user.telegram_id)
        return web.json_response({
            "user": {
                "id": user.telegram_id,
                "firstName": auth.first_name or (user.full_name or "Foydalanuvchi"),
                "lastName": auth.last_name,
                "username": auth.username,
                "photoUrl": auth.photo_url,
                "languageCode": auth.language_code,
                "isPremium": user.is_premium,
            },
            "balance": {"credits": user.credits, "freeCredits": user.free_credits, "balanceUzs": user.balance_uzs},
            "referralLink": f"https://t.me/{username}?start=ref_{user.telegram_id}",
            "referrals": referrals,
            "paymentProviders": [p.name for p in payments.online_providers],
            "botUsername": username,
            "supportUsername": settings.support_username or None,
        })

    async def tariffs(_: web.Request) -> web.Response:
        return web.json_response([
            {"key": p.key, "title": p.title.replace('"', ""), "credits": p.credits, "priceUzs": p.price,
             "badge": TARIFF_BADGES.get(p.key)}
            for p in PACKAGES.values()
        ])

    async def history(request: web.Request) -> web.Response:
        _, user = await authenticate(request)
        try:
            limit = max(1, min(50, int(request.query.get("limit", "20"))))
        except ValueError:
            limit = 20
        rows = await db.list_generations_with_files(user.telegram_id, limit)
        return web.json_response([
            {
                "id": str(gen.id),
                "type": gen.gen_type,
                "topic": gen.topic,
                "createdAt": _iso(gen.created_at),
                "status": _generation_status(gen),
                "files": [_file_json(request, f) for f in files],
            }
            for gen, files in rows
        ])

    async def create_job(request: web.Request) -> web.Response:
        _, user = await authenticate(request)
        try:
            body = await request.json()
        except Exception:
            raise ApiError(400, "So'rov noto'g'ri") from None
        if not isinstance(body, dict):
            raise ApiError(400, "So'rov noto'g'ri")
        req = _parse_job_request(body)
        uid = user.telegram_id
        if uid in ACTIVE_JOBS:
            raise ApiError(409, "Oldingi buyurtmangiz hali tayyorlanmoqda. Iltimos kuting.")
        # Reserve the slot before any await so parallel requests cannot start two jobs.
        ACTIVE_JOBS.add(uid)
        try:
            balance = await db.get_user_balance(uid)
            if balance is None or balance.total <= 0:
                raise ApiError(402, "Generatsiyalar soni tugadi")
            job = await jobs.start(uid, req, is_free=balance.uses_free_credit)
        except BaseException:
            ACTIVE_JOBS.discard(uid)
            raise
        return web.json_response(_job_json(request, job), status=201)

    async def get_job(request: web.Request) -> web.Response:
        _, user = await authenticate(request)
        try:
            job_id = int(request.match_info["job_id"])
        except ValueError:
            raise ApiError(404, "Vazifa topilmadi") from None
        job = jobs.get(job_id)
        if job is not None:
            if job.user_id != user.telegram_id:
                raise ApiError(404, "Vazifa topilmadi")
            return web.json_response(_job_json(request, job))

        gen = await db.get_generation(job_id)
        if gen is None or gen.user_id != user.telegram_id:
            raise ApiError(404, "Vazifa topilmadi")
        status = _generation_status(gen)
        files = await db.list_generated_files(gen.id) if status == "completed" else []
        return web.json_response({
            "id": str(gen.id),
            "status": status,
            "stage": "done" if status == "completed" else "rendering",
            "progress": 100 if status == "completed" else 90,
            "files": [_file_json(request, f) for f in files],
            "error": None if status != "failed" else "Generatsiya yakunlanmadi. Qayta urinib ko'ring.",
            "isFree": gen.is_free,
        })

    async def send_file(request: web.Request) -> web.Response:
        _, user = await authenticate(request)
        f = await db.get_generated_file(request.match_info["file_id"])
        if f is None or f.user_id != user.telegram_id:
            raise ApiError(404, "Fayl topilmadi")
        local = cache_path(f.id, f.name)
        try:
            if f.tg_file_id:
                await bot.send_document(user.telegram_id, f.tg_file_id)
            elif local.exists():
                sent = await bot.send_document(user.telegram_id, FSInputFile(local, filename=f.name))
                if sent.document:
                    await db.set_file_tg_id(f.id, sent.document.file_id)
            else:
                raise ApiError(410, "Fayl muddati tugagan")
        except TelegramAPIError as exc:
            logger.warning("Cannot send file %s to %s: %s", f.id, user.telegram_id, exc)
            raise ApiError(400, "Botga /start bosing, so'ng qayta urinib ko'ring") from None
        return web.json_response({"ok": True})

    async def download_file(request: web.Request) -> web.StreamResponse:
        file_id = request.match_info["file_id"]
        try:
            exp = int(request.query.get("exp", "0"))
        except ValueError:
            exp = 0
        if exp < time.time() or not hmac.compare_digest(_sign(file_id, exp), request.query.get("sig", "")):
            raise ApiError(403, "Havola muddati tugagan. Ilovadan qayta yuklab oling.")
        f = await db.get_generated_file(file_id)
        if f is None:
            raise ApiError(404, "Fayl topilmadi")

        ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", f.name).strip("_") or f"document.{f.file_format}"
        headers = {
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(f.name)}",
            "Content-Type": CONTENT_TYPES.get(f.file_format, "application/octet-stream"),
            "Cache-Control": "private, max-age=3600",
        }
        local = cache_path(f.id, f.name)
        if local.exists():
            return web.FileResponse(local, headers=headers)
        if not f.tg_file_id:
            raise ApiError(410, "Fayl muddati tugagan")
        buffer = io.BytesIO()
        try:
            await bot.download(f.tg_file_id, destination=buffer)
        except TelegramAPIError:
            logger.exception("Cannot download file %s from Telegram", f.id)
            raise ApiError(502, "Faylni yuklab bo'lmadi. Keyinroq urinib ko'ring.") from None
        data = buffer.getvalue()
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(data)
        except OSError:
            logger.debug("Cannot cache file %s", f.id, exc_info=True)
        return web.Response(body=data, headers=headers)

    async def create_payment(request: web.Request) -> web.Response:
        _, user = await authenticate(request)
        try:
            body = await request.json()
        except Exception:
            raise ApiError(400, "So'rov noto'g'ri") from None
        package = get_package(str(body.get("tariff", "")))
        provider = {"click": payments.click, "payme": payments.payme}.get(str(body.get("provider", "")))
        if package is None:
            raise ApiError(400, "Bunday tarif mavjud emas")
        if provider is None or not provider.enabled:
            raise ApiError(400, "Bu to'lov usuli hozircha ulanmagan. Karta orqali to'lang.")
        tx = await db.create_transaction(user.telegram_id, package.key, package.price, package.credits, provider=provider.name)
        url = provider.checkout_url(tx, return_url=f"https://t.me/{await get_bot_username()}")
        return web.json_response({"provider": provider.name, "url": url, "transactionId": str(tx.id)})

    async def click_prepare(request: web.Request) -> web.Response:
        result = await payments.click.handle_prepare(dict(await request.post()))
        return web.json_response(result.body, status=result.status_code)

    async def click_complete(request: web.Request) -> web.Response:
        result = await payments.click.handle_complete(dict(await request.post()))
        return web.json_response(result.body, status=result.status_code)

    async def payme_rpc(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        result = await payments.payme.handle_rpc(payload, request.headers.get("Authorization", ""))
        return web.json_response(result.body, status=result.status_code)

    app = web.Application(middlewares=[cors_middleware], client_max_size=256 * 1024)
    app.add_routes([
        web.get("/", index),
        web.get("/api/health", index),
        web.get("/api/me", me),
        web.get("/api/tariffs", tariffs),
        web.get("/api/history", history),
        web.post("/api/jobs", create_job),
        web.get("/api/jobs/{job_id}", get_job),
        web.post("/api/files/{file_id}/send", send_file),
        web.get("/api/files/{file_id}/download", download_file),
        web.post("/api/payments", create_payment),
        web.post("/api/payments/click/prepare", click_prepare),
        web.post("/api/payments/click/complete", click_complete),
        web.post("/api/payments/payme", payme_rpc),
    ])
    return app
