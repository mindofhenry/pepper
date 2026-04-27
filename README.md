# Pepper

Discord bot for Henry's personal Discord server. Two distinct user groups, one codebase:

1. **Book club**, around 8 friends. Book search, polls, per-user reading progress, section discussion threads, AI-generated discussion prompts, meeting scheduling.
2. **Media downloads**, Henry only (whitelist-enforced). Torrent search via Prowlarr, qBittorrent download orchestration, ClamAV scan, file move into Jellyfin library, library scan trigger.

Originally two bots (Paige + Scurvy). Consolidated in April 2026 with strict per-cog failure isolation.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate    # Windows
pip install -r requirements.txt

cp .env.example .env       # then fill it in
python migrate.py          # idempotent; safe to run on every deploy
python bot.py
```

## Layout

```
bot.py              # Entrypoint. Dynamic cog loader, global error handler.
config.py           # Env loading.
migrate.py          # Migration runner.
cogs/
  admin.py          # /admin reload, /admin health
  book_club/        # /book, /poll, /progress, /section
  media/            # Empty until Phase 12.
services/           # External API wrappers (Google Books, Anthropic).
shared/             # db pool, logging, error helpers.
migrations/         # NNN_*.sql, applied in order by migrate.py.
```

See [CLAUDE.md](CLAUDE.md) for full architectural detail, env var reference, and house rules.

## Where it runs

Production: **PLEX-MINI-PC** as an NSSM Windows service named `pepper`. Deploys are `git pull` plus an NSSM service restart.

Development happens on Henry's Main PC and laptop. Linear ([Pepper - Discord Bot](https://linear.app/mindofhenry/project/paige-book-club-discord-bot-681951f9eb4e)) is the source of truth for project state.
