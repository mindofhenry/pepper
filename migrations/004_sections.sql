-- Migration 004: Reading sections (bookmarks for group reading assignments).
-- Either end_chapter or end_page (or both) defines how far to read.
-- Thread is auto-created when section is opened; AI prompts are NOT auto-seeded.

CREATE TABLE IF NOT EXISTS reading_sections (
    id              BIGSERIAL PRIMARY KEY,
    guild_id        BIGINT NOT NULL,
    book_id         BIGINT NOT NULL REFERENCES books(id),
    end_chapter     INTEGER,
    end_page        INTEGER,
    thread_id       BIGINT,
    status          TEXT NOT NULL DEFAULT 'active',  -- active, closed
    created_by      BIGINT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    CHECK (end_chapter IS NOT NULL OR end_page IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_sections_guild_status ON reading_sections(guild_id, status);
