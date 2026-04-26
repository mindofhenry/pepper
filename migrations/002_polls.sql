-- Migration 002: Polls and current book tracking.
-- A poll has many nominations; after voting, one nomination wins and becomes
-- the current book for that guild.

CREATE TABLE IF NOT EXISTS books (
    id              BIGSERIAL PRIMARY KEY,
    google_id       TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    authors         TEXT[] NOT NULL DEFAULT '{}',
    page_count      INTEGER,
    thumbnail_url   TEXT,
    info_link       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS polls (
    id              BIGSERIAL PRIMARY KEY,
    guild_id        BIGINT NOT NULL,
    channel_id      BIGINT NOT NULL,
    message_id      BIGINT,
    status          TEXT NOT NULL DEFAULT 'nominating',  -- nominating, voting, closed
    winner_book_id  BIGINT REFERENCES books(id),
    created_by      BIGINT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_polls_guild_status ON polls(guild_id, status);

CREATE TABLE IF NOT EXISTS poll_nominations (
    id              BIGSERIAL PRIMARY KEY,
    poll_id         BIGINT NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    book_id         BIGINT NOT NULL REFERENCES books(id),
    nominated_by    BIGINT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (poll_id, book_id)
);

CREATE TABLE IF NOT EXISTS poll_votes (
    poll_id         BIGINT NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    nomination_id   BIGINT NOT NULL REFERENCES poll_nominations(id) ON DELETE CASCADE,
    user_id         BIGINT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (poll_id, user_id)
);

-- Current book per guild. One row per guild at most.
CREATE TABLE IF NOT EXISTS current_books (
    guild_id        BIGINT PRIMARY KEY,
    book_id         BIGINT NOT NULL REFERENCES books(id),
    set_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    set_by          BIGINT NOT NULL,
    from_poll_id    BIGINT REFERENCES polls(id)
);
