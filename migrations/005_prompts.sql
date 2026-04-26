-- Migration 005: Cached AI-generated discussion prompts.
-- Keyed by book + section endpoints so we regenerate only when inputs change.
-- Stored as JSONB array of strings.

CREATE TABLE IF NOT EXISTS discussion_prompts (
    id              BIGSERIAL PRIMARY KEY,
    book_id         BIGINT NOT NULL REFERENCES books(id),
    end_chapter     INTEGER,
    end_page        INTEGER,
    prompts_json    JSONB NOT NULL,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (book_id, end_chapter, end_page)
);

