

# Changes I may want

I may want to implement some kind of source meta-file so that I can store settings related to a
specific source. The primary purpose for this is if I want to create some kind of central symbol
database since different brokers/etc use different notation for the same assets.

A more basic option:
If i don't want a full symbol agnostic system, I could at least setup a list of aliases that should
be supported by each source. This is mainly to ensure that both EURUSD and EUR/USD work.

It would make comparisons/etc. easier. I could even set it up so that each symbol is associated with
its market.


markets:
    id (int)
    name (forex)

symbols:
    id (int)
    ticker (EUR/USD)
    market_id

aliases
    symbol_id  whatever the id is for EUR/USD
    ticker     EURUSD





