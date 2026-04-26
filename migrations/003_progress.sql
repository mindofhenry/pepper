-- Migration 003: Per-user reading progress.
-- Progress is scoped by (guild_id, user_id, book_id). A user can track the
-- same book in multiple guilds independently.

CREATE TABLE IF NOT EXISTS reading_progress (
    guild_id        BIGINT NOT NULL,
    user_id         BIGINT NOT NULL,
    book_id         BIGINT NOT NULL REFERENCES books(id),
    current_page    INTEGER,
    current_chapter INTEGER,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, user_id, book_id)
);

CREATE INDEX IF NOT EXISTS idx_progress_book ON reading_progress(book_id);
