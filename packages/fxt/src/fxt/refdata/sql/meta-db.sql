-- fxt meta database schema
-- NOTE: foreign_keys is per-connection and NOT stored in the file.
--       Run `PRAGMA foreign_keys = ON;` on every connection in your code.
PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;   -- stored in the file; bump on schema changes

CREATE TABLE IF NOT EXISTS markets (
    name    TEXT NOT NULL PRIMARY KEY
            CHECK (name <> '' AND name NOT GLOB '*[^a-z0-9_-]*')
);

CREATE TABLE IF NOT EXISTS sources (
    name    TEXT NOT NULL PRIMARY KEY
            CHECK (name <> '' AND name NOT GLOB '*[^a-z0-9_-]*'),
    website TEXT CHECK (website IS NULL OR website LIKE 'http%://%')
);

-- Your canonical (market, symbol) combinations.
-- name is the filesystem-safe form used everywhere (lake paths, metadata, CLI).
CREATE TABLE IF NOT EXISTS symbols (
    market  TEXT NOT NULL REFERENCES markets (name),
    name    TEXT NOT NULL
            CHECK (name <> '' AND name NOT GLOB '*[^A-Z0-9._-]*'),
    PRIMARY KEY (market, name)
);

-- How each source spells a canonical symbol
-- (e.g. dukascopy, forex, EURUSD -> 'EUR/USD').
CREATE TABLE IF NOT EXISTS source_symbols (
    source        TEXT NOT NULL REFERENCES sources (name),
    market        TEXT NOT NULL,
    name          TEXT NOT NULL,
    source_symbol TEXT NOT NULL CHECK (source_symbol <> ''),
    PRIMARY KEY (source, market, name),
    UNIQUE (source, source_symbol COLLATE NOCASE),  -- stored as entered
    FOREIGN KEY (market, name) REFERENCES symbols (market, name)
);

-- Nicknames, scoped per market; case-insensitive uniqueness via NOCASE.
CREATE TABLE IF NOT EXISTS symbol_aliases (
    market  TEXT NOT NULL,
    alias   TEXT NOT NULL COLLATE NOCASE CHECK (alias <> ''),
    name    TEXT NOT NULL,
    PRIMARY KEY (market, alias),
    FOREIGN KEY (market, name) REFERENCES symbols (market, name)
);

-- Canonical intervals (your names, e.g. TICK, 1MIN, 1HOUR).
-- seconds: NULL for TICK; useful for ordering and resample checks.
CREATE TABLE IF NOT EXISTS intervals (
    name    TEXT NOT NULL PRIMARY KEY
            CHECK (name <> '' AND name NOT GLOB '*[^A-Z0-9]*'),
    seconds INTEGER CHECK (seconds IS NULL OR seconds > 0)
);

-- How each source spells a canonical interval (e.g. '1H' vs '1HOUR').
CREATE TABLE IF NOT EXISTS source_intervals (
    source          TEXT NOT NULL REFERENCES sources (name),
    interval_name   TEXT NOT NULL REFERENCES intervals (name),
    source_interval TEXT NOT NULL CHECK (source_interval <> ''),
    PRIMARY KEY (source, interval_name),
    UNIQUE (source, source_interval)
);
