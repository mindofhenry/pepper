"""Environment variable loader. All secrets come from .env."""
import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_BOOKS_API_KEY: str = os.getenv("GOOGLE_BOOKS_API_KEY", "")

# Fail fast if anything critical is missing.
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing from .env")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL missing from .env")
_raw_test_guild = os.getenv("TEST_GUILD_ID", "").strip()
TEST_GUILD_ID: int | None = int(_raw_test_guild) if _raw_test_guild else None
