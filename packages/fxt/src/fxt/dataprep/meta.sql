-- Foreign keys are off by default in SQLite; enable on every connection.
PRAGMA foreign_keys = ON;

-- Asset classes (e.g. 'forex', 'us_equities', 'crypto').
-- Names are used directly as datalake directory names.
CREATE TABLE markets (
    name TEXT PRIMARY KEY
        CHECK (name <> '' AND name NOT GLOB '*[^a-z0-9_-]*')
);

-- Canonical instruments, independent of any data source.
-- 'safe' is the directory-safe form of 'name' used on disk; treat it as permanent.
CREATE TABLE symbols (
    name   TEXT PRIMARY KEY,
    safe   TEXT NOT NULL UNIQUE
        CHECK (safe <> '' AND safe NOT GLOB '*[^A-Z0-9._-]*'),
    market TEXT NOT NULL REFERENCES markets(name)
);

-- Data providers. Each BaseSource subclass registers here by name.
CREATE TABLE sources (
    name    TEXT PRIMARY KEY,
    website TEXT
        CHECK (website IS NULL OR website LIKE 'http%://%')
);

-- Per-source symbol mappings and source-specific details.
-- Each source has exactly one symbol per canonical instrument, and vice versa.
CREATE TABLE source_symbols (
    source TEXT NOT NULL REFERENCES sources(name),
    symbol TEXT NOT NULL,
    name   TEXT NOT NULL REFERENCES symbols(name),
    PRIMARY KEY (source, symbol),
    UNIQUE (source, name)
);
