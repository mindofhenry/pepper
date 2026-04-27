"""Environment variable loader. All secrets come from .env."""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Core (book club) ---
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

_raw_admin_channel = os.getenv("ADMIN_CHANNEL_ID", "").strip()
ADMIN_CHANNEL_ID: int | None = int(_raw_admin_channel) if _raw_admin_channel else None

# --- Media (Phase 12+; loaded as plain strings/ints, validated when used) ---
QB_HOST: str = os.getenv("QB_HOST", "")
QB_USER: str = os.getenv("QB_USER", "")
QB_PASS: str = os.getenv("QB_PASS", "")
PROWLARR_URL: str = os.getenv("PROWLARR_URL", "")
PROWLARR_API_KEY: str = os.getenv("PROWLARR_API_KEY", "")
STAGING_DIR: str = os.getenv("STAGING_DIR", "")
JELLYFIN_URL: str = os.getenv("JELLYFIN_URL", "")
JELLYFIN_API_KEY: str = os.getenv("JELLYFIN_API_KEY", "")
CLAMAV_HOST: str = os.getenv("CLAMAV_HOST", "")

_raw_whitelist = os.getenv("MEDIA_USER_WHITELIST", "").strip()
MEDIA_USER_WHITELIST: list[int] = (
    [int(x) for x in _raw_whitelist.split(",") if x.strip()]
    if _raw_whitelist
    else []
)
