#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from __future__ import annotations
import difflib
import logging
import re
from typing import ClassVar

from pydantic import Field
import dukascopy_python as dp
import dukascopy_python.instruments as dp_instruments

#fxt 
from fxt.descriptors import cached_classproperty
from fxt.data.markets import BaseMarket, MarketRegistry

#local
from ._registry import SourceRegistry
from .base import BaseSource






#!================================================================================(80)
#! setup (logging, exceptions, etc)
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)


from fxt import get_env
DEFAULT_MAX_RETRIES = get_env('DOWNLOADER_MAX_RETRIES')



def _detect_dukascopy_market(symbol: str) -> str:
    """ Detects the market/asset class of a Dukascopy symbol based on its syntax.

        print(detect_dukascopy_market("EUR/USD"))        # Output: forex
        print(detect_dukascopy_market("BRENT.CMD/USD"))  # Output: commodities
        print(detect_dukascopy_market("USA30.IDX/USD"))  # Output: indices
        print(detect_dukascopy_market("AAPL.US/USD"))    # Output: equities
        print(detect_dukascopy_market("BTCUSD"))         # Output: crypto

        Written by gemini, so we'll see.
    """
    if not symbol:
        return "unknown"
        
    symbol_upper = symbol.upper().strip()
    
    # 1. Commodities check (.CMD)
    if ".CMD" in symbol_upper:
        return "commodities"
        
    # 2. Indices check (.IDX)
    if ".IDX" in symbol_upper:
        return "indices"
        
    # 3. Equities check (typically contain exchange tags like .US, .DE, .UK, etc. or stock format)
    # Dukascopy equities often look like 'AAPL.US/USD' or similar patterns
    if re.search(r'\.[A-Z]{2}/', symbol_upper) and not (".CMD" in symbol_upper or ".IDX" in symbol_upper):
        return "equities"
        
    # 4. Crypto check (common crypto tickers paired with USD)
    crypto_bases = {"BTC", "ETH", "LTC", "BCH", "XRP", "ADA", "DOT", "LINK"}
    base_candidate = symbol_upper.replace("/", "")[:3]
    if base_candidate in crypto_bases or "USDT" in symbol_upper:
        return "crypto"
        
    # 5. Default fallback to Forex (standard 6-letter pairs or standard FX notation)
    # e.g., 'EURUSD', 'EUR/USD', 'GBP_JPY'
    clean_fx = symbol_upper.replace("/", "").replace("_", "")
    if len(clean_fx) == 6 and clean_fx.isalpha():
        return "forex"
        
    return "other"
#



#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
@SourceRegistry.register('fake')
class FakeSource(BaseSource):
    """ Fake source class used for testing.

        Going to basically be dukascopy settings.
    """
    #~======================================================================(70)
    #~ private (specific to this class)
    #~----------------------------------------------------------------------(70)
    @classmethod
    def _build_map(cls, prefix: str, module) -> dict[str, str]:
        """ Map UPPERCASED value -> original value for every `prefix*` constant in `module`.
            The original value is what the library actually expects.
        """
        mapping: dict[str, str] = {}
        for attr in dir(module):
            if attr.startswith(prefix):
                original = str(getattr(module, attr))
                mapping.setdefault(original.upper(), original)
        return mapping
    #

    #! private stuff to handle sorting intervals
    _INTERVAL_UNITS: ClassVar[dict[str,int]] = {
        "SEC": 1,
        "MIN": 60,
        "HOUR": 3600,
        "DAY": 86400,
        "WEEK": 604800,
        "MONTH": 2592000,  # approximated as 30 days
    }
    _INTERVAL_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"^(\d+)(SEC|MIN|HOUR|DAY|WEEK|MONTH)$")

    @classmethod
    def _interval_to_seconds(cls, interval: str) -> int:
        """Convert an interval string like '15min' to its duration in seconds.

            'tick' is treated as 0 so it sorts first.
        """
        interval = interval.upper()

        #~ special cases
        if interval == "TICK":
            return 0

        #if you need to add typehints to the following..
        match: re.Match[str]|None = cls._INTERVAL_PATTERN.match(interval)
        if not match:
            raise ValueError(f"Unrecognised interval: {interval!r}")
        
        count, unit = match.groups()
        return int(count) * cls._INTERVAL_UNITS[unit]
    #
    @classmethod
    def _sort_intervals(cls, interval_map:dict[str,str], reverse:bool=False) -> dict[str,str]:
        """ Sorts the interval map using the keys.
        """
        return dict(
            sorted(
                interval_map.items(),
                key=lambda item: cls._interval_to_seconds(item[0]), #item[0] = use uppercase key
                reverse=reverse,
            )
        )
    #

    
    #~======================================================================(70)
    #~ required class properties
    #~----------------------------------------------------------------------(70)
    id:str = Field(default="fake")
    method:str = Field(default="fake-python-lib")
    TICK:str = Field(default=dp.INTERVAL_TICK, exclude=True)

    @cached_classproperty
    def SYMBOL_MAP(cls) -> dict[str, str]:
        #normal symbols
        sym:dict[str, str] = cls._build_map("INSTRUMENT_", dp_instruments)
        #add fake currency 
        sym.setdefault("FAK/USD", "FAK/USD")
        
        #return cls._build_map("INSTRUMENT_", dp_instruments)
        return sym
    #
 
    @cached_classproperty
    def INTERVAL_MAP(cls) -> dict[str, str]:
        """
        """
        #print("INSIDE INTERVAL_MAP()")
        return cls._sort_intervals(
            cls._build_map("INTERVAL_", dp)
        )
    #
    
    @classmethod
    def which_market(cls, symbol:str) -> BaseMarket|None:
        """ 
        """
        #get string name of market
        mkt = _detect_dukascopy_market(symbol)

        # print(f"DUKA SOIRCE : which_market({symbol}) - mkt: {mkt}")
        # print(f"market in registry: {mkt in MarketRegistry}")
        # print(MarketRegistry[mkt])

        #convert that to a dealie
        from class_registry import RegistryKeyError
        try:
            market = MarketRegistry[mkt]
        except RegistryKeyError as e:
            logger.warning(f"which_market() found unregistered market: {e}")
            raise

        return market
    #



    #~======================================================================(70)
    #~ utils
    #~----------------------------------------------------------------------(70)


#-


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):

    #! TO RUN: pixi run python -m fxt.data.sources.fake

    from datetime import datetime
    from rich import print

    source = FakeSource()


    def test_symbols(src):
        print()
        print("[bold cyan]* intervals[/]")
        print(src.INTERVALS)
        print("[bold cyan]* intervals (sorted...)[/]")
        print(src._sort_intervals(src.INTERVAL_MAP))
        

        print()
        print("[bold cyan]* symbols[/]")
        print(f" - # symbols: {len(src.SYMBOLS)}")
        print(f" - first few: {src.SYMBOLS[:5]}")
    #
    test_symbols(source)


    #! searching for symbols
    def test_symbol_search(src):
        symbols = [
            'fak/usd',
            'eur/usd',
            'GBp/USd',
            'GBPJPY'
        ]
        print()
        print("[bold cyan]* symbol search[/]")
        for sym in symbols:
            try:
                api_value = src.get_symbol(sym)
                mkt = src.which_market(api_value)
                #mkt = _detect_dukascopy_market(api_value)
                print(
                    f" - looking for: [bold]{sym}[/], [bold]found: [green]{api_value}[/]"
                    f" -- mkt: [orchid2]{mkt}[/]"
                )
            except ValueError as e:
                print(f" - looking for: [bold]{sym}[/], [bold red]SYMBOL NOT FOUND[/], error: {e}")
    #
    test_symbol_search(source)




    #! searching for intervals
    def test_interval_search(src):
        intervals = [
            '4hour',
            '30m',
            '1MIN'
        ]
        print()
        print("[bold cyan]* interval search[/]")
        for inter in intervals:
            try:
                api_value = src.get_interval(inter)
                print(f" - looking for: [bold]{inter}[/], [bold]found: [green]{api_value}[/]")
            except ValueError as e:
                print(f" - looking for: [bold]{inter}[/], [bold red]INTERVAL NOT FOUND[/], error: {e}")
    #
    test_interval_search(source)


    #! testing model dump
    def test_source_model_dump(src):
        print()
        print("[bold cyan]* trying model dump[/]")
        
        print(f" - [cyan]dump[/]: {src.model_dump()}")
        print(f" - [cyan]dump_json[/]: {src.model_dump_json()}")
    #
    test_source_model_dump(source)

    print()
