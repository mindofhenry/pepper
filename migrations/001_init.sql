-- Migration 001: Initial schema.
-- Creates the migrations tracking table plus the events logging table.
-- Every new table from here on must include guild_id for multi-guild support.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
    id              BIGSERIAL PRIMARY KEY,
    event_name      TEXT NOT NULL,
    user_id         BIGINT,
    guild_id        BIGINT,
    metadata_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index on common query patterns: "all events for a guild", "all events of type X".
CREATE INDEX IF NOT EXISTS idx_events_guild_id ON events(guild_id);
CREATE INDEX IF NOT EXISTS idx_events_event_name ON events(event_name);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);
