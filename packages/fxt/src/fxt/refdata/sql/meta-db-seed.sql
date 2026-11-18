-- fxt meta database: starting data
-- Run after meta_schema.sql. Inserts are ordered to satisfy foreign keys.
PRAGMA foreign_keys = ON;

BEGIN;

-- Sources -------------------------------------------------------------
INSERT INTO sources (name, website) VALUES
    ('dukascopy', 'https://www.dukascopy.com');

-- Markets -------------------------------------------------------------
INSERT INTO markets (name) VALUES
    ('forex');

-- Intervals -----------------------------------------------------------
-- seconds is NULL for TICK: it has no fixed duration.
INSERT INTO intervals (name, seconds) VALUES
    ('TICK', NULL);
--  ('1MIN',  60),
--  ('1HOUR', 3600);

-- Dukascopy's spelling, as used by dukascopy_python.
-- Confirm with: python -c "import dukascopy_python as dp; print(dp.INTERVAL_TICK)"
INSERT INTO source_intervals (source, interval_name, source_interval) VALUES
    ('dukascopy', 'TICK', 'TICK');
--  ('dukascopy', '1MIN',  '1MIN'),
--  ('dukascopy', '1HOUR', '1HOUR');

-- Symbols (filesystem-safe names) -------------------------------------
INSERT INTO symbols (market, name) VALUES
    -- majors
    ('forex', 'EURUSD'),
    ('forex', 'USDJPY'),
    ('forex', 'GBPUSD'),
    ('forex', 'USDCHF'),
    ('forex', 'AUDUSD'),
    ('forex', 'USDCAD'),
    ('forex', 'NZDUSD'),
    -- crosses
    ('forex', 'EURJPY'),
    ('forex', 'GBPJPY'),
    ('forex', 'EURGBP'),
    ('forex', 'EURCHF'),
    ('forex', 'EURAUD'),
    ('forex', 'EURCAD'),
    ('forex', 'GBPCHF'),
    ('forex', 'GBPAUD'),
    ('forex', 'AUDJPY'),
    ('forex', 'CADJPY'),
    ('forex', 'CHFJPY'),
    ('forex', 'NZDJPY'),
    ('forex', 'AUDNZD');

-- Dukascopy's spelling of each symbol --------------------------------
INSERT INTO source_symbols (source, market, name, source_symbol) VALUES
    ('dukascopy', 'forex', 'EURUSD', 'EUR/USD'),
    ('dukascopy', 'forex', 'USDJPY', 'USD/JPY'),
    ('dukascopy', 'forex', 'GBPUSD', 'GBP/USD'),
    ('dukascopy', 'forex', 'USDCHF', 'USD/CHF'),
    ('dukascopy', 'forex', 'AUDUSD', 'AUD/USD'),
    ('dukascopy', 'forex', 'USDCAD', 'USD/CAD'),
    ('dukascopy', 'forex', 'NZDUSD', 'NZD/USD'),
    ('dukascopy', 'forex', 'EURJPY', 'EUR/JPY'),
    ('dukascopy', 'forex', 'GBPJPY', 'GBP/JPY'),
    ('dukascopy', 'forex', 'EURGBP', 'EUR/GBP'),
    ('dukascopy', 'forex', 'EURCHF', 'EUR/CHF'),
    ('dukascopy', 'forex', 'EURAUD', 'EUR/AUD'),
    ('dukascopy', 'forex', 'EURCAD', 'EUR/CAD'),
    ('dukascopy', 'forex', 'GBPCHF', 'GBP/CHF'),
    ('dukascopy', 'forex', 'GBPAUD', 'GBP/AUD'),
    ('dukascopy', 'forex', 'AUDJPY', 'AUD/JPY'),
    ('dukascopy', 'forex', 'CADJPY', 'CAD/JPY'),
    ('dukascopy', 'forex', 'CHFJPY', 'CHF/JPY'),
    ('dukascopy', 'forex', 'NZDJPY', 'NZD/JPY'),
    ('dukascopy', 'forex', 'AUDNZD', 'AUD/NZD');

-- Common trader nicknames ---------------------------------------------
INSERT INTO symbol_aliases (market, alias, name) VALUES
    ('forex', 'fiber',   'EURUSD'),
    ('forex', 'gopher',  'USDJPY'),
    ('forex', 'cable',   'GBPUSD'),
    ('forex', 'swissie', 'USDCHF'),
    ('forex', 'aussie',  'AUDUSD'),
    ('forex', 'loonie',  'USDCAD'),
    ('forex', 'kiwi',    'NZDUSD'),
    ('forex', 'guppy',   'GBPJPY'),
    ('forex', 'chunnel', 'EURGBP');

COMMIT;
