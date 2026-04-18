-- Migration 001: add tags, card_tags, and study_sets tables

CREATE TABLE tags (
    id       SERIAL  PRIMARY KEY,
    deck_id  INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    name     TEXT    NOT NULL
);
CREATE UNIQUE INDEX ix_tags_deck_id_name ON tags (deck_id, lower(name));

CREATE TABLE card_tags (
    card_id  INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (card_id, tag_id)
);

CREATE TABLE study_sets (
    id         SERIAL    PRIMARY KEY,
    deck_id    INTEGER   NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    name       TEXT      NOT NULL,
    tag_query  TEXT      NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
