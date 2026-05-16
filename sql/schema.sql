-- VibéVocab Schema

-- Users
-- email is the login identifier (matched against the OAuth provider's returned email)
CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    email       TEXT        NOT NULL UNIQUE,
    name        TEXT        NOT NULL,
    avatar_url  TEXT,
    is_admin    BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP   NOT NULL DEFAULT NOW()
);

-- Decks (private per user)
-- source_language and target_language are BCP 47 codes (e.g. en-US, pt-PT)
CREATE TABLE decks (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name             TEXT        NOT NULL,
    source_language  TEXT        NOT NULL,
    target_language  TEXT        NOT NULL,
    created_at       TIMESTAMP   NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP   NOT NULL DEFAULT NOW()
);

-- Cards (words and expressions)
-- part_of_speech: noun, verb, adjective, expression, etc.
-- gender: masculine, feminine (nullable; used for nouns)
-- expression_audio: TTS clip for target_expression (mono, low bitrate)
-- example_audio:    TTS clip for target_example (mono, low bitrate)
CREATE TABLE cards (
    id                 SERIAL PRIMARY KEY,
    deck_id            INTEGER     NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    source_expression  TEXT        NOT NULL,
    source_example     TEXT,
    target_expression  TEXT        NOT NULL,
    target_example     TEXT,
    part_of_speech     TEXT CHECK (part_of_speech IN (
                           'noun', 'verb', 'adjective', 'adverb', 'pronoun',
                           'preposition', 'conjunction', 'interjection', 'expression',
                           'other'
                       )),
    noun_gender        TEXT,       -- masculine, feminine (nouns only)
    noun_is_plural     BOOLEAN     NOT NULL DEFAULT FALSE,
    notes              TEXT,
    expression_audio   BYTEA,
    example_audio      BYTEA,
    created_at         TIMESTAMP   NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMP   NOT NULL DEFAULT NOW()
);

-- SRS state per user per card (SM-2)
-- ease_factor:   SM-2 ease factor, starts at 2.5
-- interval_days: days until next review
-- repetitions:   consecutive correct reviews
CREATE TABLE card_progress (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    card_id          INTEGER     NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    ease_factor      REAL        NOT NULL DEFAULT 2.5,
    interval_days    INTEGER     NOT NULL DEFAULT 1,
    repetitions      INTEGER     NOT NULL DEFAULT 0,
    next_review_at   TIMESTAMP   NOT NULL DEFAULT NOW(),
    last_reviewed_at TIMESTAMP,
    created_at       TIMESTAMP   NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP   NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, card_id)
);

-- User preference for audio playback per deck
-- audio_preference: expression, example, both
CREATE TABLE deck_preferences (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    deck_id          INTEGER     NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    audio_preference TEXT        NOT NULL DEFAULT 'both',
    UNIQUE (user_id, deck_id)
);

-- Tags (scoped to a deck, stored as-entered, unique by lowercase within a deck)
CREATE TABLE tags (
    id       SERIAL  PRIMARY KEY,
    deck_id  INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    name     TEXT    NOT NULL
);
CREATE UNIQUE INDEX ix_tags_deck_id_name ON tags (deck_id, lower(name));

-- Cards <-> Tags (many-to-many)
CREATE TABLE card_tags (
    card_id  INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (card_id, tag_id)
);

-- Study sets (named tag queries scoped to a deck)
-- query: tag expression string, e.g. "food AND NOT advanced"
CREATE TABLE study_sets (
    id         SERIAL    PRIMARY KEY,
    deck_id    INTEGER   NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    name       TEXT      NOT NULL,
    tag_query  TEXT      NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Single-row table updated on every write transaction; used to detect DB changes.
CREATE TABLE db_state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    last_modified  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_backup_at TIMESTAMPTZ
);
INSERT INTO db_state (id) VALUES (1);

-- Review history
-- quality_score:    SM-2 quality 0–5
-- response_time_ms: time from card display to answer submission
-- was_overridden:   user marked a wrong answer as correct (typo)
CREATE TABLE review_log (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    card_id          INTEGER     NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    typed_answer     TEXT        NOT NULL,
    quality_score    INTEGER     NOT NULL CHECK (quality_score BETWEEN 0 AND 5),
    response_time_ms INTEGER     NOT NULL,
    was_overridden   BOOLEAN     NOT NULL DEFAULT FALSE,
    reviewed_at      TIMESTAMP   NOT NULL DEFAULT NOW()
);
