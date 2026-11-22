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
-- EUR > GBP > AUD > NZD > USD > CAD > CHF > JPY
INSERT INTO symbols (market, name) VALUES
    -- majors
    ('forex', 'EURUSD'), -- have
    ('forex', 'GBPUSD'), -- have
    ('forex', 'AUDUSD'), -- have
    ('forex', 'NZDUSD'), -- have
    ('forex', 'USDCAD'), -- ! need
    ('forex', 'USDCHF'), -- ! need
    ('forex', 'USDJPY'), -- have
    
    -- crosses
    ('forex', 'EURAUD'), -- have
    ('forex', 'EURCAD'), -- ! need
    ('forex', 'EURCHF'), -- have
    ('forex', 'EURGBP'), -- have
    ('forex', 'EURJPY'), -- have
    ('forex', 'EURNZD'), -- have
    
    ('forex', 'GBPAUD'), -- have
    ('forex', 'GBPCAD'), -- have
    ('forex', 'GBPCHF'), -- have
    ('forex', 'GBPJPY'), -- have
    ('forex', 'GBPNZD'), -- ~ needs transferred

    ('forex', 'AUDCAD'), -- ! need
    ('forex', 'AUDCHF'), -- ! need (dl now)
    ('forex', 'AUDJPY'), -- have
    ('forex', 'AUDNZD'), -- ! need
    
    ('forex', 'NZDCAD'), -- ! need
    ('forex', 'NZDCHF'), -- ! need
    ('forex', 'NZDJPY'), -- have

    ('forex', 'CADCHF'), -- ! need
    ('forex', 'CADJPY'), -- have

    ('forex', 'CHFJPY'); -- have
    

-- Dukascopy's spelling of each symbol --------------------------------
INSERT INTO source_symbols (source, market, name, source_symbol) VALUES
    -- majors
    ('dukascopy', 'forex', 'EURUSD', 'EUR-USD'),
    ('dukascopy', 'forex', 'GBPUSD', 'GBP-USD'),
    ('dukascopy', 'forex', 'AUDUSD', 'AUD-USD'),
    ('dukascopy', 'forex', 'NZDUSD', 'NZD-USD'),
    ('dukascopy', 'forex', 'USDCAD', 'USD-CAD'),
    ('dukascopy', 'forex', 'USDCHF', 'USD-CHF'),
    ('dukascopy', 'forex', 'USDJPY', 'USD-JPY'),
    

    ('dukascopy', 'forex', 'EURAUD', 'EUR-AUD'),
    ('dukascopy', 'forex', 'EURCAD', 'EUR-CAD'),
    ('dukascopy', 'forex', 'EURCHF', 'EUR-CHF'),    
    ('dukascopy', 'forex', 'EURGBP', 'EUR-GBP'),
    ('dukascopy', 'forex', 'EURJPY', 'EUR-JPY'),
    ('dukascopy', 'forex', 'EURNZD', 'EUR-NZD'),   

    ('dukascopy', 'forex', 'GBPAUD', 'GBP-AUD'),
    ('dukascopy', 'forex', 'GBPCAD', 'GBP-CAD'),
    ('dukascopy', 'forex', 'GBPCHF', 'GBP-CHF'),
    ('dukascopy', 'forex', 'GBPJPY', 'GBP-JPY'),
    ('dukascopy', 'forex', 'GBPNZD', 'GBP-NZD'),

    ('dukascopy', 'forex', 'AUDCAD', 'AUD-CAD'),
    ('dukascopy', 'forex', 'AUDCHF', 'AUD-CHF'),
    ('dukascopy', 'forex', 'AUDJPY', 'AUD-JPY'),
    ('dukascopy', 'forex', 'AUDNZD', 'AUD-NZD'),

    ('dukascopy', 'forex', 'NZDCAD', 'NZD-CAD'),
    ('dukascopy', 'forex', 'NZDCHF', 'NZD-CHF'),
    ('dukascopy', 'forex', 'NZDJPY', 'NZD-JPY'),

    ('dukascopy', 'forex', 'CADCHF', 'CAD-CHF'),
    ('dukascopy', 'forex', 'CADJPY', 'CAD-JPY'),
    
    ('dukascopy', 'forex', 'CHFJPY', 'CHF-JPY');


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
