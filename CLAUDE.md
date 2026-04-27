# [CLAUDE.md](http://CLAUDE.md)

This file is the project context for Claude Code working in `C:\Dev\pepper`. Read it fully before doing anything else in any session.

---

## Project Summary

Pepper is a Discord bot for Henry's personal Discord server. It serves two distinct user groups in one codebase:

1. **Book club** (\~8 friends) — book search, polls, per-user reading progress, section discussion threads, AI-generated discussion prompts, meeting scheduling.
2. **Media downloads** (Henry only, whitelist-enforced) — torrent search via Prowlarr, qBittorrent download orchestration, ClamAV scan, file move into Jellyfin library, library scan trigger.

Originally two separate bots (Paige + Scurvy). Consolidated into one bot in April 2026 with strict failure isolation between cogs.

- **Repo:** <https://github.com/mindofhenry/pepper>
- **Linear project:** <https://linear.app/mindofhenry/project/paige-book-club-discord-bot-681951f9eb4e> (URL slug is stale; project is named "Pepper - Discord Bot")
- **Linear is the source of truth for project state.** Phases, milestones, active issues, and completion status all live there. Do not track project state in this file.

---

## Where Work Happens

MachineRolePathUserMain PCPrimary dev`C:\Dev\pepperhhmar`Hanktop (laptop)Secondary dev`C:\Dev\pepperhhmar`PLEX-MINI-PCRuntime (NSSM service `pepper`)`C:\Dev\pepperHenry`

- All coding happens on Main PC or Hanktop. Both have SSH profiles for the Mini-PC.
- The bot **runs only on PLEX-MINI-PC** as an NSSM-managed Windows service named `pepper`.
- Testing the running bot is done via RDP into the Mini-PC from the dev machine.
- Deployment is `git pull` on the Mini-PC followed by an NSSM service restart.
- Mini-PC currently has a legacy `C:\Dev\scurvy` directory from the old Scurvy bot. This will be decommissioned after the Pepper deploy lands.
- **No more Linode for this bot.** Linode hosts other infra (n8n, Cloudflare Tunnel) but not Pepper.

---

## Tech Stack

- **Language:** Python 3.11+ (venv at `C:\Dev\pepper\.venv` on each machine)
- **Discord library:** [discord.py](http://discord.py) (latest stable, async)
- **Database:** Neon Postgres via `asyncpg` (max_size=5, Neon free tier naps idle conns)
- **AI:** Anthropic Claude Haiku via official `anthropic` Python SDK
- **Book data:** Google Books API
- **Torrent client:** qBittorrent (Web API on `localhost:8080`, listening port `55011` bound to PIA WireGuard adapter `wgpia0`)
- **Indexer:** Prowlarr (Windows install on Mini-PC, web UI at `http://10.0.0.80:9696`, API at `/api/v1/search`)
- **Cloudflare bypass:** FlareSolverr in Docker on Mini-PC at `http://localhost:8191`, wired into Prowlarr as an Indexer Proxy (tag: `cloudflare`). Used for indexers behind Cloudflare anti-bot (e.g. 1337x).
- **Antivirus:** ClamAV (Windows build) for downloaded file scans before library move
- **Media server integration:** Jellyfin API (library scan trigger)
- **VPN:** PIA WireGuard, adapter `wgpia0`, kill switch Always, port forwarding ON
- **Container runtime:** Docker on the Mini-PC (and on the Linode). Either machine can host containers; choose based on what the service needs (FlareSolverr lives on Mini-PC because Prowlarr is local).
- **Hosting:** PLEX-MINI-PC, NSSM-managed Windows service named `pepper`
- **Repo:** Private GitHub repo at `mindofhenry/pepper`
- **Secrets:** `.env` file (gitignored, loaded via `python-dotenv`)

---

## Commands

```bash
# One-time setup (any machine)
python -m venv .venv
.venv\Scripts\activate    # Windows
pip install -r requirements.txt

# Apply pending DB migrations (idempotent; run on every deploy)
python migrate.py

# Run the bot locally for dev/smoke testing
python bot.py
```

There is no test suite, linter, or formatter configured. `.env` supplies all secrets and config — see `.env.example` for the full list.

### Command sync behavior

`bot.py` on_ready branches on `TEST_GUILD_ID`: if set, commands are copied and synced per-guild (instant, for dev). If unset, it does a global sync (takes up to an hour to propagate). Leave `TEST_GUILD_ID` set during development; unset for prod deploys.

---

## Architecture

All async. Three layers:

- `bot.py` — entrypoint. Initializes logging, creates the `commands.Bot`, calls `db.init_pool()` in `setup_hook`, then dynamically discovers and loads cogs from `cogs/book_club/` and `cogs/media/`, plus explicitly loads `cogs/admin.py`.
- `cogs/` — feature modules organized by domain. Each cog defines a `commands.Cog` subclass with an `app_commands.Group`, a `cog_command_error` handler, and exports an `async def setup(bot)` that [discord.py](http://discord.py) calls on load.
- `services/` — external API wrappers (`google_books.py`, `anthropic_client.py`, `qbittorrent.py`, `prowlarr.py`, `clamav.py`, `jellyfin.py`). Keep HTTP/SDK concerns out of cogs. Cogs orchestrate, services do the actual work.
- `shared/` — cross-cutting infra: `db.py` (asyncpg pool, the only place that touches Postgres), `logging.py` (structured logging setup), `errors.py` (shared error helpers/classes).

### Target module layout (post-MIN-54)

```
pepper/
├── bot.py                 # Dynamic cog loader, global error handler
├── config.py              # Env loading
├── cogs/
│   ├── __init__.py
│   ├── book_club/
│   │   ├── __init__.py
│   │   ├── search.py      # /book search, lookup
│   │   ├── polls.py       # /poll
│   │   ├── progress.py    # /progress
│   │   ├── sections.py    # /section new, current, close
│   │   ├── prompts.py     # /section prompts (AI-generated, cached)
│   │   └── meetings.py    # /meeting (Phase 8)
│   ├── media/
│   │   ├── __init__.py
│   │   ├── search.py      # Phase 14
│   │   ├── download.py    # Phase 12
│   │   ├── pipeline.py    # Phase 13
│   │   └── status.py      # Phase 15
│   └── admin.py           # /admin reload <cog>, /admin health
├── services/
│   ├── __init__.py
│   ├── google_books.py
│   ├── anthropic_client.py
│   ├── qbittorrent.py
│   ├── prowlarr.py
│   ├── clamav.py
│   └── jellyfin.py
├── shared/
│   ├── __init__.py
│   ├── db.py
│   ├── logging.py
│   └── errors.py
├── migrations/
│   └── NNN_*.sql
├── requirements.txt
├── .env.example
└── README.md
```

> **Current state note:** as of MIN-54 kickoff, the codebase is still in the original flat-cog Linode layout (`cogs/books.py`, `cogs/polls.py`, `cogs/progress.py`, `cogs/sections.py` at the top of `cogs/`, plus a top-level `db.py`). MIN-54 is the refactor that produces the layout above. If you are working on MIN-54, this section is your target; if you are working post-MIN-54, this section is the current state.

### Architectural principles (non-negotiable)

1. **Cogs do not import across cog boundaries.** Book club code never imports from media code and vice versa. Shared logic goes in `services/` or `shared/`, never in another cog.
2. **Per-cog failure isolation.** Every cog has a `cog_command_error` handler. A failure in one cog must not crash the bot or affect other cogs. This is the architectural payoff of the merge — losing it makes the consolidation pointless.
3. **Per-cog error boundaries log to a private admin channel.** Failures are visible to Henry without crashing the bot.
4. **Multi-guild from day one.** Every database table has a `guild_id` column. No hardcoded server IDs.
5. **Instrument everything.** Every slash command invocation, poll, thread, prompt generation, download, and pipeline event writes to the `events` table. Non-negotiable.
6. **Cache AI calls.** Discussion prompts for a given `(book_id, end_chapter, end_page)` tuple are generated once and reused from Postgres. Never regenerate.
7. **Async everywhere.** [discord.py](http://discord.py), asyncpg, the Anthropic SDK, and all service clients (qBittorrent, Prowlarr, Jellyfin, ClamAV) are async. **No blocking calls in event handlers.** Any blocking I/O must be wrapped in `asyncio.to_thread()`.
8. **Defer first on any command that does I/O** (`await interaction.response.defer()`, then `followup.send`). Google Books, Anthropic, Postgres, Prowlarr, qBittorrent all easily exceed Discord's 3s initial-response window.
9. **Secrets via** `.env`**.** Never commit tokens. `python-dotenv` loads them. `.env` is gitignored.

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
- **One active poll and one active section per guild.** Cogs guard on this before inserting.
- **Poll voting uses Discord reactions, not a votes table.** `poll_votes` exists in schema but the close tally reads reactions off `polls.message_id` (subtracting 1 for the bot's own reaction). Don't "fix" this without changing the start/close flow together.
- **Log events for every user action.** Pattern: call the command's mutation, then `await db.log_event(...)` with a stable `event_name` and useful `metadata`. This is the analytics surface.
- **No em-dashes in user-facing text** (commit messages, bot replies, embeds, error messages). Henry hates them. Use commas, periods, parentheses, or colons instead.

---

## Media-Specific Rules (Locked)

These were debated and settled. Don't relitigate without explicit user request.

1. **All media commands require a user whitelist.** The bot is not a public download proxy. Phase 12+ cogs must check the whitelist before processing any media command.
2. **VPN leak prevention is two layers, not three:** qBittorrent interface binding to `wgpia0` + PIA kill switch Always. A Windows Firewall outbound layer was tried and removed — it broke HTTPS trackers (`WSAEACCES 10013`).
3. **VPN must be active before any qBittorrent operation.** Pre-flight VPN check is required for all media commands and is surfaced via `/admin health`. This is MIN-52.
4. **PIA: never use US Streaming Optimized servers.** They don't support port forwarding. Vancouver (Auto CA Vancouver) is the known-working server.
5. **Never expose magnet links in user-facing flows.** Internal/test commands only.
6. **Don't rebuild Scurvy from scratch.** Phase 1 of the original Scurvy work was 88% complete — port it during Phase 12, don't rewrite.
7. **Movies vs. TV detection** in Phase 13 is an open question (heuristic vs user-specified at download time). Ask Henry before implementing.

---

## Adding Features

1. **New book club cog** → create `cogs/book_club/<name>.py` with a Cog class, an `app_commands.Group`, a `cog_command_error` handler, and `async def setup(bot)`. The dynamic loader picks it up automatically.
2. **New media cog** → same pattern under `cogs/media/<name>.py`. Must check the user whitelist before processing any command. Must check VPN status before any qBittorrent/Prowlarr operation.
3. **Schema change** → new `migrations/NNN_<name>.sql` (next integer). Include `guild_id` on any new feature table. Migrations run inside a single transaction that also inserts into `schema_migrations`.
4. **External API** → add a service module under `services/`, never inline in a cog. Cogs orchestrate, services do the work.
5. **New env variable** → add it to `.env.example` with a placeholder and a comment, and document it in this file under Environment Variables below.

---

## Environment Variables (.env)

Current and planned keys:

**Core (book club):**

- `DISCORD_TOKEN` — bot token
- `DATABASE_URL` — Neon Postgres connection string
- `ANTHROPIC_API_KEY` — for Haiku discussion prompts
- `GOOGLE_BOOKS_API_KEY` — book lookups
- `TEST_GUILD_ID` — set during dev for instant slash command sync; unset for prod
- `ADMIN_CHANNEL_ID` — private channel for cog error reports

**Media (Phase 12+):**

- `QB_HOST` — qBittorrent host (typically `http://localhost:8080`)
- `QB_USER` — qBittorrent Web UI username
- `QB_PASS` — qBittorrent Web UI password
- `PROWLARR_URL` — Prowlarr base URL (typically `http://10.0.0.80:9696`)
- `PROWLARR_API_KEY` — Prowlarr API key (Settings → General → Security)
- `STAGING_DIR` — path on Mini-PC external drive for completed downloads (TBD, ask Henry)
- `JELLYFIN_URL` — Jellyfin base URL
- `JELLYFIN_API_KEY` — Jellyfin API key for library scan trigger
- `CLAMAV_HOST` — ClamAV daemon host
- `MEDIA_USER_WHITELIST` — comma-separated Discord user IDs allowed to use media commands
- `COMCAST_IP_PREFIX` — for MIN-52 VPN pre-flight check (proposed)
- `EXPECTED_VPN_COUNTRY` — alternate proposal for MIN-52 (proposed)

If a needed env var is missing, stop and ask Henry rather than guessing.

---

## Planning With Files

For any multi-step task (2+ distinct tasks), Claude Code must maintain three files at the repo root:

- `findings.md` — observations, surprising discoveries, things that changed your understanding mid-task
- `progress.md` — running log of what's been done, in order
- `task_plan.md` — the plan itself, with checkboxes; updated as steps complete or get reordered

**These files must be updated at the end of every step, not just at the end of the session.** If a step changes the plan, update `task_plan.md` immediately. If a discovery invalidates an assumption, write it in `findings.md` before moving on.

If these files don't exist at the start of a multi-step task, create them. If they exist from a previous session, read them first and continue from where they left off.

These three files are gitignored (or should be). They are working memory, not deliverables.

---

## Division of Labor

- **This file / Claude Code:** multi-step coding work, file edits, refactors, cogs implementation, running migrations, smoke tests.
- **Henry's chat with Claude (web/app):** specs, architecture decisions, single-file edits, troubleshooting diagnosis, Linear updates, planning.

If you find yourself needing an architectural decision mid-task, stop and ask rather than improvising.

---

## House Rules

- **Brutal honesty, no echo-chambering, no overengineering.** Simplest fix that works. If a proposed solution is over-built, say so.
- **Always specify which machine** in any instruction or commit message — Main PC, Hanktop, or PLEX-MINI-PC. Never assume.
- **PowerShell over GUI** on Windows. No screenshots-as-instructions.
- **Web-search current pricing** before recommending any paid hardware, software, or service.
- **Don't commit secrets.** `.env` is gitignored; keep it that way. If you add a new env var, add it to `.env.example` and document it in this file.
- **Don't push to** `main` **without confirmation.** Branch, commit, and let Henry review before merging.
- **Linear is the source of truth.** Update Linear at the end of any session with meaningful change.

---

## Open Questions (ask Henry before assuming)

- Staging folder path on Mini-PC external drive (`STAGING_DIR`, needed for Phase 13).
- qBittorrent Web UI username/password (`QB_USER`, `QB_PASS`).
- MIN-52 check style: IP prefix (`COMCAST_IP_PREFIX`) or country (`EXPECTED_VPN_COUNTRY`).
- Movies vs. TV detection in Phase 13: heuristic-based or user-specified at download time.
- Natural language parsing in Phase 14: regex heuristics, small Haiku call, or stay literal.
