import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _int_set(raw: str) -> frozenset[int]:
    result = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            result.add(int(part))
    return frozenset(result)


def _str_tuple(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def _path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    bot_token: str
    gemini_api_key: str
    gemini_model: str
    gemini_fallback_models: tuple[str, ...]
    admin_ids: frozenset[int]
    admin_chat_id: int | None
    max_concurrent_jobs: int
    database_path: Path
    temp_dir: Path
    libreoffice_path: str
    log_level: str

    # billing
    free_credits_on_start: int
    referral_bonus_credits: int
    payment_card_number: str
    payment_card_holder: str
    support_username: str
    watermark_text: str

    # online providers (stubs until merchant accounts are connected)
    click_enabled: bool
    click_service_id: str
    click_merchant_id: str
    click_secret_key: str
    payme_enabled: bool
    payme_merchant_id: str
    payme_secret_key: str


def load_settings() -> Settings:
    bot_token = _str("BOT_TOKEN")
    gemini_api_key = _str("GEMINI_API_KEY")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN .env faylida ko'rsatilmagan")
    if not gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY .env faylida ko'rsatilmagan")

    admin_ids = _int_set(_str("ADMIN_IDS"))
    admin_chat_raw = _str("ADMIN_CHAT_ID")
    if admin_chat_raw.lstrip("-").isdigit():
        admin_chat_id: int | None = int(admin_chat_raw)
    else:
        admin_chat_id = min(admin_ids) if admin_ids else None

    settings = Settings(
        bot_token=bot_token,
        gemini_api_key=gemini_api_key,
        gemini_model=_str("GEMINI_MODEL", "gemini-3.8-flash") or "gemini-3.8-flash",
        gemini_fallback_models=_str_tuple(_str("GEMINI_FALLBACK_MODELS", "gemini-flash-latest,gemini-2.5-flash")),
        admin_ids=admin_ids,
        admin_chat_id=admin_chat_id,
        max_concurrent_jobs=max(1, _int("MAX_CONCURRENT_JOBS", 3)),
        database_path=_path(_str("DATABASE_PATH", "data/slidecraft.db")),
        temp_dir=_path(_str("TEMP_DIR", "data/tmp")),
        libreoffice_path=_str("LIBREOFFICE_PATH"),
        log_level=_str("LOG_LEVEL", "INFO").upper() or "INFO",
        free_credits_on_start=max(0, _int("FREE_CREDITS_ON_START", 1)),
        referral_bonus_credits=max(0, _int("REFERRAL_BONUS_CREDITS", 1)),
        payment_card_number=_str("PAYMENT_CARD_NUMBER", "8600 0000 0000 0000"),
        payment_card_holder=_str("PAYMENT_CARD_HOLDER", "Ism Familiya"),
        support_username=_str("SUPPORT_USERNAME").lstrip("@"),
        watermark_text=_str("WATERMARK_TEXT", "SlideCraft AI orqali tayyorlandi — @slaydreferat_aibot"),
        click_enabled=_bool("CLICK_ENABLED"),
        click_service_id=_str("CLICK_SERVICE_ID"),
        click_merchant_id=_str("CLICK_MERCHANT_ID"),
        click_secret_key=_str("CLICK_SECRET_KEY"),
        payme_enabled=_bool("PAYME_ENABLED"),
        payme_merchant_id=_str("PAYME_MERCHANT_ID"),
        payme_secret_key=_str("PAYME_SECRET_KEY"),
    )
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return settings


settings = load_settings()
