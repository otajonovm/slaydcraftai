from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, false
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("credits >= 0", name="ck_users_credits_non_negative"),
        CheckConstraint("free_credits >= 0", name="ck_users_free_credits_non_negative"),
        CheckConstraint("balance_uzs >= 0", name="ck_users_balance_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(64))
    language_code: Mapped[str | None] = mapped_column(String(16))
    balance_uzs: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # Paid credits: documents are generated without watermark.
    credits: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # Trial / referral credits: documents get a watermark on the last page.
    free_credits: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    referrer_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    @property
    def total_credits(self) -> int:
        return self.credits + self.free_credits


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True
    )
    package: Mapped[str] = mapped_column(String(32), nullable=False, default="custom")
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_added: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)   # manual, balance, click, payme
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)  # pending, completed, cancelled
    receipt_image: Mapped[str | None] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    admin_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class GenerationHistory(Base):
    __tablename__ = "generations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True
    )
    gen_type: Mapped[str] = mapped_column(String(16), nullable=False)   # presentation, referat
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    params: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    cost_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="processing", nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class GeneratedFile(Base):
    """A file produced by a generation; the Telegram file_id keeps it downloadable after dyno restarts."""

    __tablename__ = "generated_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    generation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("generations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(8), nullable=False)  # pptx, docx, pdf
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tg_file_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


@dataclass(frozen=True, slots=True)
class UserBalance:
    credits: int
    free_credits: int
    balance_uzs: int

    @property
    def total(self) -> int:
        return self.credits + self.free_credits

    @property
    def uses_free_credit(self) -> bool:
        """Paid credits are always spent first, so a watermark only applies when none are left."""
        return self.credits <= 0
