import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from database.models import Base, GenerationHistory, Transaction, User, UserBalance, utcnow

logger = logging.getLogger(__name__)


def _today_start_utc() -> datetime:
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)


def _prepare_schema(conn) -> None:
    """Create tables and migrate the pre-billing (aiosqlite) schema if it is present."""
    columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()]
    legacy = "user_id" in columns and "telegram_id" not in columns
    has_legacy_generations = False
    if legacy:
        logger.warning("Legacy schema detected, migrating users and generations")
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.exec_driver_sql("ALTER TABLE users RENAME TO users_legacy")
        has_legacy_generations = bool(
            conn.exec_driver_sql(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='generations'"
            ).fetchone()
        )
        if has_legacy_generations:
            conn.exec_driver_sql("ALTER TABLE generations RENAME TO generations_legacy")

    Base.metadata.create_all(conn)

    if legacy:
        conn.exec_driver_sql(
            """
            INSERT INTO users (telegram_id, full_name, username, language_code, balance_uzs, credits,
                               free_credits, is_premium, is_blocked, created_at, last_seen_at)
            SELECT user_id, full_name, username, language_code, 0, 0, 1, 0, is_blocked, created_at, last_seen_at
            FROM users_legacy
            """
        )
        if has_legacy_generations:
            conn.exec_driver_sql(
                """
                INSERT INTO generations (user_id, gen_type, topic, params, cost_credits, is_free, status,
                                         error, created_at, finished_at)
                SELECT user_id, kind, topic, params, 0, 1, status, error, created_at, finished_at
                FROM generations_legacy
                """
            )
            conn.exec_driver_sql("DROP TABLE generations_legacy")
        conn.exec_driver_sql("DROP TABLE users_legacy")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        logger.warning("Legacy migration finished")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    # --------------------------------------------------------------- lifecycle

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_async_engine(f"sqlite+aiosqlite:///{self.path.as_posix()}", pool_pre_ping=True)

        @event.listens_for(self._engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        async with self._engine.begin() as conn:
            await conn.run_sync(_prepare_schema)
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)

        async with self.session() as s, s.begin():
            await s.execute(
                update(GenerationHistory)
                .where(GenerationHistory.status == "processing")
                .values(status="failed", error="interrupted", finished_at=utcnow())
            )
        logger.info("Database connected: %s", self.path)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    def session(self) -> AsyncSession:
        if self._sessionmaker is None:
            raise RuntimeError("Database is not connected")
        return self._sessionmaker()

    # ------------------------------------------------------------------ users

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: str | None,
        full_name: str | None,
        language_code: str | None,
        free_credits: int = 1,
    ) -> tuple[User, bool]:
        """Returns (user, created)."""
        try:
            async with self.session() as s, s.begin():
                user = await s.scalar(select(User).where(User.telegram_id == telegram_id))
                if user is not None:
                    user.username = username
                    user.full_name = full_name
                    user.language_code = language_code
                    user.last_seen_at = utcnow()
                    return user, False
                user = User(
                    telegram_id=telegram_id,
                    username=username,
                    full_name=full_name,
                    language_code=language_code,
                    credits=0,
                    free_credits=free_credits,
                    balance_uzs=0,
                )
                s.add(user)
                await s.flush()
                return user, True
        except IntegrityError:
            # Two updates from the same new user raced; the other one created the row.
            user = await self.get_user(telegram_id)
            if user is None:
                raise
            return user, False

    async def get_user(self, telegram_id: int) -> User | None:
        async with self.session() as s:
            return await s.scalar(select(User).where(User.telegram_id == telegram_id))

    async def get_user_balance(self, telegram_id: int) -> UserBalance | None:
        async with self.session() as s:
            row = (
                await s.execute(
                    select(User.credits, User.free_credits, User.balance_uzs).where(User.telegram_id == telegram_id)
                )
            ).first()
        if row is None:
            return None
        return UserBalance(credits=row.credits, free_credits=row.free_credits, balance_uzs=row.balance_uzs)

    async def add_credit(self, telegram_id: int, amount: int, free: bool = False) -> bool:
        if amount <= 0:
            raise ValueError("amount must be positive")
        column = User.free_credits if free else User.credits
        async with self.session() as s, s.begin():
            result = await s.execute(
                update(User).where(User.telegram_id == telegram_id).values({column.key: column + amount})
            )
            return result.rowcount > 0

    async def add_balance(self, telegram_id: int, amount_uzs: int) -> bool:
        if amount_uzs <= 0:
            raise ValueError("amount must be positive")
        async with self.session() as s, s.begin():
            result = await s.execute(
                update(User)
                .where(User.telegram_id == telegram_id)
                .values(balance_uzs=User.balance_uzs + amount_uzs)
            )
            return result.rowcount > 0

    async def deduct_credit(
        self, telegram_id: int, use_free: bool, generation_id: int | None = None
    ) -> str | None:
        """Atomically spends one credit. Returns the spent bucket ("credits"/"free_credits") or None."""
        order = (User.free_credits, User.credits) if use_free else (User.credits, User.free_credits)
        async with self.session() as s, s.begin():
            for column in order:
                result = await s.execute(
                    update(User)
                    .where(User.telegram_id == telegram_id, column > 0)
                    .values({column.key: column - 1})
                )
                if result.rowcount:
                    if generation_id is not None:
                        await s.execute(
                            update(GenerationHistory)
                            .where(GenerationHistory.id == generation_id)
                            .values(cost_credits=1, is_free=column.key == "free_credits")
                        )
                    return column.key
        return None

    async def add_referral(self, new_user_id: int, referrer_id: int, bonus_credits: int) -> bool:
        """Links a freshly registered user to the referrer and rewards the referrer once."""
        if new_user_id == referrer_id:
            return False
        async with self.session() as s, s.begin():
            referrer_exists = await s.scalar(select(User.id).where(User.telegram_id == referrer_id))
            if not referrer_exists:
                return False
            linked = await s.execute(
                update(User)
                .where(User.telegram_id == new_user_id, User.referrer_id.is_(None))
                .values(referrer_id=referrer_id)
            )
            if not linked.rowcount:
                return False
            if bonus_credits > 0:
                await s.execute(
                    update(User)
                    .where(User.telegram_id == referrer_id)
                    .values(free_credits=User.free_credits + bonus_credits)
                )
            return True

    async def count_referrals(self, telegram_id: int) -> int:
        async with self.session() as s:
            return int(await s.scalar(select(func.count(User.id)).where(User.referrer_id == telegram_id)) or 0)

    # ----------------------------------------------------------- transactions

    async def create_transaction(
        self, user_id: int, package: str, amount: int, credits: int, provider: str = "manual"
    ) -> Transaction:
        async with self.session() as s, s.begin():
            tx = Transaction(
                user_id=user_id, package=package, amount=amount, credits_added=credits, provider=provider,
                status="pending",
            )
            s.add(tx)
            await s.flush()
            return tx

    async def cancel_unpaid_transactions(self, user_id: int) -> int:
        """Cancels the user's pending manual transactions that have no receipt yet."""
        async with self.session() as s, s.begin():
            result = await s.execute(
                update(Transaction)
                .where(
                    Transaction.user_id == user_id,
                    Transaction.status == "pending",
                    Transaction.provider == "manual",
                    Transaction.receipt_image.is_(None),
                )
                .values(status="cancelled", updated_at=utcnow())
            )
            return result.rowcount

    async def attach_receipt(self, tx_id: int, file_id: str) -> bool:
        async with self.session() as s, s.begin():
            result = await s.execute(
                update(Transaction)
                .where(Transaction.id == tx_id, Transaction.status == "pending")
                .values(receipt_image=file_id, updated_at=utcnow())
            )
            return result.rowcount > 0

    async def get_transaction(self, tx_id: int) -> Transaction | None:
        async with self.session() as s:
            return await s.get(Transaction, tx_id)

    async def get_transaction_by_external_id(self, provider: str, external_id: str) -> Transaction | None:
        async with self.session() as s:
            return await s.scalar(
                select(Transaction).where(Transaction.provider == provider, Transaction.external_id == external_id)
            )

    async def set_transaction_external_id(self, tx_id: int, provider: str, external_id: str) -> bool:
        async with self.session() as s, s.begin():
            result = await s.execute(
                update(Transaction)
                .where(Transaction.id == tx_id, Transaction.status == "pending")
                .values(provider=provider, external_id=external_id, updated_at=utcnow())
            )
            return result.rowcount > 0

    async def complete_transaction(self, tx_id: int, admin_id: int | None = None) -> Transaction | None:
        """pending -> completed and credits are added in one DB transaction. None if already processed."""
        async with self.session() as s, s.begin():
            result = await s.execute(
                update(Transaction)
                .where(Transaction.id == tx_id, Transaction.status == "pending")
                .values(status="completed", admin_id=admin_id, updated_at=utcnow())
            )
            if not result.rowcount:
                return None
            tx = await s.get(Transaction, tx_id)
            await s.execute(
                update(User)
                .where(User.telegram_id == tx.user_id)
                .values(credits=User.credits + tx.credits_added, is_premium=True)
            )
            return tx

    async def cancel_transaction(self, tx_id: int, admin_id: int | None = None) -> Transaction | None:
        async with self.session() as s, s.begin():
            result = await s.execute(
                update(Transaction)
                .where(Transaction.id == tx_id, Transaction.status == "pending")
                .values(status="cancelled", admin_id=admin_id, updated_at=utcnow())
            )
            if not result.rowcount:
                return None
            return await s.get(Transaction, tx_id)

    async def pay_from_balance(self, user_id: int, package: str, price: int, credits: int) -> Transaction | None:
        async with self.session() as s, s.begin():
            result = await s.execute(
                update(User)
                .where(User.telegram_id == user_id, User.balance_uzs >= price)
                .values(
                    balance_uzs=User.balance_uzs - price,
                    credits=User.credits + credits,
                    is_premium=True,
                )
            )
            if not result.rowcount:
                return None
            tx = Transaction(
                user_id=user_id, package=package, amount=price, credits_added=credits,
                provider="balance", status="completed",
            )
            s.add(tx)
            await s.flush()
            return tx

    async def list_pending_transactions(self, limit: int = 10) -> list[Transaction]:
        async with self.session() as s:
            rows = await s.scalars(
                select(Transaction)
                .where(Transaction.status == "pending", Transaction.receipt_image.is_not(None))
                .order_by(Transaction.id)
                .limit(limit)
            )
            return list(rows)

    # ------------------------------------------------------------ generations

    async def create_generation(
        self, user_id: int, gen_type: str, topic: str, params: dict[str, Any], is_free: bool
    ) -> int:
        async with self.session() as s, s.begin():
            gen = GenerationHistory(
                user_id=user_id,
                gen_type=gen_type,
                topic=topic[:500],
                params=json.dumps(params, ensure_ascii=False),
                cost_credits=0,
                is_free=is_free,
            )
            s.add(gen)
            await s.flush()
            return gen.id

    async def finish_generation(self, generation_id: int, success: bool, error: str | None = None) -> None:
        async with self.session() as s, s.begin():
            await s.execute(
                update(GenerationHistory)
                .where(GenerationHistory.id == generation_id)
                .values(
                    status="success" if success else "failed",
                    error=(error or "")[:1000] or None,
                    finished_at=utcnow(),
                )
            )

    async def get_user_stats(self, telegram_id: int) -> dict[str, int]:
        ok = GenerationHistory.status == "success"
        async with self.session() as s:
            row = (
                await s.execute(
                    select(
                        func.count(GenerationHistory.id).filter(ok).label("total"),
                        func.count(GenerationHistory.id).filter(ok, GenerationHistory.gen_type == "presentation").label("presentations"),
                        func.count(GenerationHistory.id).filter(ok, GenerationHistory.gen_type == "referat").label("referats"),
                    ).where(GenerationHistory.user_id == telegram_id)
                )
            ).one()
        return {"total": row.total or 0, "presentations": row.presentations or 0, "referats": row.referats or 0}

    async def get_recent_generations(self, telegram_id: int, limit: int = 5) -> list[GenerationHistory]:
        async with self.session() as s:
            rows = await s.scalars(
                select(GenerationHistory)
                .where(GenerationHistory.user_id == telegram_id, GenerationHistory.status == "success")
                .order_by(GenerationHistory.id.desc())
                .limit(limit)
            )
            return list(rows)

    async def get_global_stats(self) -> dict[str, int]:
        today = _today_start_utc()
        gen_ok = GenerationHistory.status == "success"
        paid = (Transaction.status == "completed") & (Transaction.provider != "balance")
        async with self.session() as s:
            users = await s.scalar(select(func.count(User.id)))
            users_today = await s.scalar(select(func.count(User.id)).where(User.created_at >= today))
            premium = await s.scalar(select(func.count(User.id)).where(User.is_premium.is_(True)))
            referred = await s.scalar(select(func.count(User.id)).where(User.referrer_id.is_not(None)))
            gen = (
                await s.execute(
                    select(
                        func.count(GenerationHistory.id).filter(gen_ok).label("total"),
                        func.count(GenerationHistory.id).filter(gen_ok, GenerationHistory.gen_type == "presentation").label("presentations"),
                        func.count(GenerationHistory.id).filter(gen_ok, GenerationHistory.gen_type == "referat").label("referats"),
                        func.count(GenerationHistory.id).filter(GenerationHistory.status == "failed").label("failed"),
                        func.count(GenerationHistory.id).filter(gen_ok, GenerationHistory.created_at >= today).label("today"),
                    )
                )
            ).one()
            revenue = await s.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(paid))
            revenue_today = await s.scalar(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(paid, Transaction.updated_at >= today)
            )
            pending = await s.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.status == "pending", Transaction.receipt_image.is_not(None)
                )
            )
        return {
            "users": users or 0,
            "users_today": users_today or 0,
            "premium": premium or 0,
            "referred": referred or 0,
            "total": gen.total or 0,
            "presentations": gen.presentations or 0,
            "referats": gen.referats or 0,
            "failed": gen.failed or 0,
            "today": gen.today or 0,
            "revenue": revenue or 0,
            "revenue_today": revenue_today or 0,
            "pending": pending or 0,
        }
