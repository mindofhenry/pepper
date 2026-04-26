# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Discord bot (discord.py + slash commands) for a friends' book club. Postgres (Neon) for state, Google Books for lookups, Anthropic Haiku for on-demand discussion prompts.

## Commands

```bash
# One-time setup
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Apply pending DB migrations (idempotent; run on every deploy)
python migrate.py

# Run the bot
python bot.py
```

There is no test suite, linter, or formatter configured. `.env` supplies `DISCORD_TOKEN`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `GOOGLE_BOOKS_API_KEY`, and optional `TEST_GUILD_ID`.

## Command sync behavior

`bot.py` on_ready branches on `TEST_GUILD_ID`: if set, commands are copied+synced per-guild (instant, for dev). If unset, it does a global sync (takes up to an hour to propagate). Leave `TEST_GUILD_ID` set during development; unset for prod deploys.

## Architecture

Three layers, all async:

- **`bot.py`** — entrypoint. Initializes logging, creates the `commands.Bot`, calls `db.init_pool()` in `setup_hook`, then loads each cog in the `COGS` list. New cogs only take effect when added to that list.
- **`cogs/*.py`** — feature modules. Each defines a `commands.Cog` subclass with an `app_commands.Group` (`/book`, `/poll`, `/progress`, `/section`) and exports an `async def setup(bot)` that discord.py calls on load.
- **`services/`** — external API wrappers (`google_books.py`, `anthropic_client.py`). Keep HTTP/SDK concerns out of cogs.
- **`db.py`** — the only place that touches Postgres. Owns a module-level asyncpg pool (created once, max_size=5 because Neon free tier naps idle conns). Cogs call `db.pool()` to acquire connections and `db.log_event(...)` for instrumentation.

### Data model

Migrations in `migrations/NNN_*.sql` are applied in order by `migrate.py`, tracked in `schema_migrations`. Every feature table carries `guild_id` — the bot is explicitly multi-guild. Key tables:

- `books` — deduped on `google_id` (upserted via `db.upsert_book`).
- `polls` → `poll_nominations` → votes recorded as Discord reactions on `polls.message_id`, then tallied at close time. Status flow: `nominating` → `voting` → `closed`.
- `current_books` — one row per guild; set when a poll closes.
- `reading_sections` — one `active` per guild; auto-creates a Discord thread, archives it on close.
- `reading_progress` — PK `(guild_id, user_id, book_id)`.
- `discussion_prompts` — cache for Haiku-generated prompts, keyed `(book_id, end_chapter, end_page)`. Lookup uses `IS NOT DISTINCT FROM` because `end_chapter`/`end_page` are nullable.
- `events` — append-only log written by every command via `db.log_event`; failures there are swallowed so instrumentation can't crash a command.

### Cross-cutting conventions

- **Slash commands only.** No prefix commands in user-facing flows.
- **Defer first on any command that does I/O** (`await interaction.response.defer()`), then `followup.send`. Google Books + Anthropic + Postgres easily exceed Discord's 3s initial-response window.
- **One active poll and one active section per guild.** Cogs guard on this before inserting.
- **Poll voting uses Discord reactions, not a votes table.** `poll_votes` exists in schema but the close tally reads reactions off `polls.message_id` (subtracting 1 for the bot's own reaction). Don't "fix" this without changing the start/close flow together.
- **Log events for every user action.** Pattern: call the command's mutation, then `await db.log_event(...)` with a stable `event_name` and useful `metadata`. This is the analytics surface.

## Adding features

1. New cog → create `cogs/<name>.py` with a Cog class, an `app_commands.Group`, and `async def setup(bot)`. Add `"cogs.<name>"` to `COGS` in `bot.py`.
2. Schema change → new `migrations/NNN_<name>.sql` (next integer). Include `guild_id` on any new feature table. Migrations run inside a single transaction that also inserts into `schema_migrations`.
3. External API → add a service module under `services/`, not inline in a cog.
