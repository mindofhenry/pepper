"""Migration runner. Applies any migrations/NNN_*.sql files not yet recorded
in schema_migrations. Idempotent and safe to run on every deploy."""
import asyncio
import logging
import re
from pathlib import Path

import asyncpg

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("migrate")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def get_applied_versions(conn: asyncpg.Connection) -> set[int]:
    """Return the set of migration versions already applied."""
    # schema_migrations may not exist on first run; guard against that.
    try:
        rows = await conn.fetch("SELECT version FROM schema_migrations")
        return {r["version"] for r in rows}
    except asyncpg.UndefinedTableError:
        return set()


def discover_migrations() -> list[tuple[int, Path]]:
    """Find all migration files matching NNN_*.sql, sorted by version."""
    pattern = re.compile(r"^(\d+)_.*\.sql$")
    found = []
    for path in MIGRATIONS_DIR.iterdir():
        match = pattern.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    return sorted(found, key=lambda x: x[0])


async def main() -> None:
    conn = await asyncpg.connect(config.DATABASE_URL)
    try:
        applied = await get_applied_versions(conn)
        log.info("Already applied: %s", sorted(applied) or "none")

        for version, path in discover_migrations():
            if version in applied:
                continue
            log.info("Applying migration %03d: %s", version, path.name)
            sql = path.read_text()
            # Run the SQL and record the version in one transaction.
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)",
                    version,
                )
            log.info("Applied %03d", version)

        log.info("Migrations complete.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
