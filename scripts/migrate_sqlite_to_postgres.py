"""One-time copy of the local SQLite database into PostgreSQL (e.g. Heroku Postgres).

Usage:
    DATABASE_URL=postgres://... python scripts/migrate_sqlite_to_postgres.py [path/to/slidecraft.db]

Rows that already exist in the target (same primary key / telegram_id) are skipped, so the script is safe
to run more than once.
"""

import asyncio
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from config import settings  # noqa: E402
from database import Database  # noqa: E402
from database.models import GenerationHistory, Transaction, User  # noqa: E402

DATETIME_COLUMNS = {"created_at", "last_seen_at", "updated_at", "finished_at"}
BOOL_COLUMNS = {"is_premium", "is_blocked", "is_free"}


def _convert(row: sqlite3.Row) -> dict:
    data = dict(row)
    for key, value in data.items():
        if key in DATETIME_COLUMNS and isinstance(value, str):
            data[key] = datetime.fromisoformat(value)
        elif key in BOOL_COLUMNS and value is not None:
            data[key] = bool(value)
    return data


async def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else settings.database_path
    if settings.database_url.startswith("sqlite"):
        raise SystemExit("DATABASE_URL must point to PostgreSQL")
    if not source.is_file():
        raise SystemExit(f"SQLite file not found: {source}")

    # Opening through Database also upgrades a legacy SQLite schema to the current one.
    local = Database(f"sqlite+aiosqlite:///{source.as_posix()}")
    await local.connect()
    await local.close()

    conn = sqlite3.connect(source)
    conn.row_factory = sqlite3.Row
    tables = [
        (User, "users", "telegram_id"),
        (Transaction, "transactions", "id"),
        (GenerationHistory, "generations", "id"),
    ]

    target = Database(settings.database_url)
    await target.connect()
    async with target.session() as s, s.begin():
        for model, table, conflict_key in tables:
            rows = [_convert(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
            if rows:
                stmt = insert(model).values(rows).on_conflict_do_nothing(index_elements=[conflict_key])
                result = await s.execute(stmt)
                print(f"{table}: {len(rows)} rows read, {result.rowcount} inserted")
            else:
                print(f"{table}: empty")
            await s.execute(
                text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                     f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)")
            )
    await target.close()
    conn.close()
    print("Done")


if __name__ == "__main__":
    asyncio.run(main())
