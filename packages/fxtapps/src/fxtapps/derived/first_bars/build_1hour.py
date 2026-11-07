""" 
Resample bars -> coarser bars (default 1MIN -> 1HOUR), one symbol-year at a time.

Reads only the finer bars (never raw ticks) and writes the coarser bars to the derived tier.
Shared helpers come from build_bars_1m for now; once a third step exists, move them into a
common module (Check, lake_path, report, verify_placement, _scan, _scalar, _close).
"""
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from typing import ClassVar
from pathlib import Path
import duckdb
from rich import print

# adjust this import to wherever build_bars_1m.py lives in your package
from .build_1min import Check, lake_path, report, verify_placement, _scan, _scalar, _close

class INTERVALS:
    INTERVAL_1MIN:ClassVar[str] = "1MIN"
    INTERVAL_1HOUR:ClassVar[str] = "1HOUR"





#!================================================================================(80)
#! main 
#!--------------------------------------------------------------------------------(80)
def resample_bars(
    lake: Path, 
    source: str,
    market: str, 
    symbol: str, 
    year: int,
    src_interval: str = INTERVALS.INTERVAL_1MIN, 
    dst_interval: str = INTERVALS.INTERVAL_1HOUR,
    bucket: str = "INTERVAL 1 HOUR",
    overwrite: bool = False
) -> Path:
    src = lake_path(lake, "derived", source, market, symbol, src_interval, year)
    out = lake_path(lake, "derived", source, market, symbol, dst_interval, year)
    if not src.exists():
        raise FileNotFoundError(src)
    if out.exists() and not overwrite:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.tmp")  # write-then-rename: a crash never leaves a partial file

    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    # Source bars have unique `time`, so first/last within a bucket is unambiguous (no tie-breaking needed).
    # Columns are qualified (s.) because the output column `time` has the same name as the input column.
    con.execute(f"""
        COPY (
            SELECT
                time_bucket({bucket}, s.time) AS time,
                arg_min(s.bid_open, s.time) AS bid_open, max(s.bid_high) AS bid_high,
                min(s.bid_low) AS bid_low,               arg_max(s.bid_close, s.time) AS bid_close,
                arg_min(s.ask_open, s.time) AS ask_open, max(s.ask_high) AS ask_high,
                min(s.ask_low) AS ask_low,               arg_max(s.ask_close, s.time) AS ask_close,
                arg_min(s.mid_open, s.time) AS mid_open, max(s.mid_high) AS mid_high,
                min(s.mid_low) AS mid_low,               arg_max(s.mid_close, s.time) AS mid_close,
                sum(s.bid_volume) AS bid_volume, sum(s.ask_volume) AS ask_volume,
                sum(s.tick_count)::UINTEGER AS tick_count,
                sum(s.spread_mean * s.tick_count) / sum(s.tick_count) AS spread_mean,  -- tick-weighted
                min(s.spread_min) AS spread_min, max(s.spread_max) AS spread_max,
                count(*)::UINTEGER AS src_bar_count      -- how many source bars had ticks (bars are sparse)
            FROM {_scan(src)} s
            GROUP BY 1
            ORDER BY 1
        ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 3)
    """)
    tmp.replace(out)
    return out
#


#!================================================================================(80)
#! testing
#!--------------------------------------------------------------------------------(80)
def verify_resampled(
    dst: Path, 
    src: Path, 
    year: int, 
    bucket: str = "INTERVAL 1 HOUR", #used in the SQL
    sample: int = 200, 
    seed: int = 42
) -> list[Check]:
    """
    """
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    d = _scan(dst)
    s = _scan(src)
    q = lambda where: _scalar(con, f"SELECT count(*) FROM {d} WHERE {where}")
    out = []

    # structure
    n = _scalar(con, f"SELECT count(*) - count(DISTINCT time) FROM {d}")
    out.append(Check("time unique", n == 0, f"{n} dupes"))
    n = _scalar(con, f"""SELECT count(*) FROM (
        SELECT time < lag(time) OVER (ORDER BY file_row_number) AS bad FROM {d}) WHERE bad""")
    out.append(Check("time sorted", n == 0, f"{n} out-of-order"))
    out.append(Check("time bucket-aligned", q(f"time != time_bucket({bucket}, time)") == 0))
    out.append(Check("all bars in year", q(f"year(time) != {year}") == 0))

    # OHLC consistency, per series
    for ser in ("bid", "ask", "mid"):
        o, h, l, c = (f"{ser}_{x}" for x in ("open", "high", "low", "close"))
        n = q(f"{l} > {h} OR {o} NOT BETWEEN {l} AND {h} OR {c} NOT BETWEEN {l} AND {h}")
        out.append(Check(f"{ser} OHLC consistent", n == 0, f"{n} bad bars"))
    out.append(Check("tick_count > 0", q("tick_count <= 0") == 0))
    out.append(Check("spread stats ordered",
                     q("spread_min < 0 OR spread_mean < spread_min - 1e-12 OR spread_mean > spread_max + 1e-12") == 0))

    # reconciliation with the source bars
    n_dst, n_src = _scalar(con, f"SELECT sum(tick_count) FROM {d}"), _scalar(con, f"SELECT sum(tick_count) FROM {s}")
    out.append(Check("tick_count sums match source", n_dst == n_src, f"{n_dst} vs {n_src}"))
    n_dst, n_src = _scalar(con, f"SELECT sum(src_bar_count) FROM {d}"), _scalar(con, f"SELECT count(*) FROM {s}")
    out.append(Check("src_bar_count sums to source rows", n_dst == n_src, f"{n_dst} vs {n_src}"))
    ext = con.execute(f"""SELECT (SELECT max(bid_high) FROM {d}) - (SELECT max(bid_high) FROM {s}),
                                 (SELECT min(bid_low)  FROM {d}) - (SELECT min(bid_low)  FROM {s}),
                                 (SELECT max(ask_high) FROM {d}) - (SELECT max(ask_high) FROM {s}),
                                 (SELECT min(ask_low)  FROM {d}) - (SELECT min(ask_low)  FROM {s})""").fetchone()
    out.append(Check("global high/low match source", all(abs(x) < 1e-12 for x in ext), str(ext))) #type: ignore
    bd, ad, bs, as_ = con.execute(f"""SELECT (SELECT sum(bid_volume) FROM {d}), (SELECT sum(ask_volume) FROM {d}), 
                                             (SELECT sum(bid_volume) FROM {s}), (SELECT sum(ask_volume) FROM {s})""").fetchone()  #type: ignore
    out.append(Check("volume totals match source", _close(bd, bs) and _close(ad, as_),
                     f"bid {bd} vs {bs}; ask {ad} vs {as_}"))

    # independent recompute of random bars from the source bars (join + ordered aggregates)
    bad = _scalar(con, f"""
        WITH picks AS MATERIALIZED (
            SELECT * FROM {d} USING SAMPLE reservoir({sample} ROWS) REPEATABLE ({seed})),
        ref AS (
            SELECT p.time,
                   first(x.bid_open  ORDER BY x.time) AS bo, last(x.bid_close ORDER BY x.time) AS bc,
                   first(x.mid_open  ORDER BY x.time) AS mo, last(x.mid_close ORDER BY x.time) AS mc,
                   max(x.ask_high) AS ah, min(x.bid_low) AS bl,
                   sum(x.tick_count) AS n, count(*) AS nb,
                   sum(x.spread_mean * x.tick_count) / sum(x.tick_count) AS sm
            FROM picks p JOIN {s} x ON x.time >= p.time AND x.time < p.time + {bucket}
            GROUP BY p.time)
        SELECT count(*) FROM picks p JOIN ref USING (time)
        WHERE abs(p.bid_open - ref.bo) > 1e-12 OR abs(p.bid_close - ref.bc) > 1e-12
           OR abs(p.mid_open - ref.mo) > 1e-12 OR abs(p.mid_close - ref.mc) > 1e-12
           OR abs(p.ask_high - ref.ah) > 1e-12 OR abs(p.bid_low - ref.bl) > 1e-12
           OR p.tick_count != ref.n OR p.src_bar_count != ref.nb OR abs(p.spread_mean - ref.sm) > 1e-9""")
    out.append(Check(f"{sample}-bar spot check vs source", bad == 0, f"{bad} mismatches"))
    return out
#



#!================================================================================(80)
#! entry point
#!--------------------------------------------------------------------------------(80)
def resample_and_verify(
    lake: Path,
    source: str,
    market: str,
    symbol: str,
    year: int,
    src_interval: str = INTERVALS.INTERVAL_1MIN,
    dst_interval: str = INTERVALS.INTERVAL_1HOUR,
    bucket: str = "INTERVAL 1 HOUR",
    overwrite: bool = False,
    force: bool = False
) -> bool:
    src = lake_path(lake, "derived", source, market, symbol, src_interval, year)
    src_checks = verify_placement(src)
    if not force and not all(c.passed for c in src_checks):
        print("[red]Source checks failed - not building.[/red]")
        report(src_checks)
        return False
    dst = resample_bars(lake, source, market, symbol, year, src_interval, dst_interval, bucket, overwrite)
    checks = src_checks + verify_placement(dst) + verify_resampled(dst, src, year, bucket)

    return report(checks, label="resample_and_verify")




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from collections.abc import Sequence
    from fxt.term import hr, clear, pause
    
    LAKE = Path("datalake/lake")
    SOURCE:str = "dukascopy"
    MARKET:str = "forex"
    SYMBOL:str = "EURJPY"
    YEARS:int|Sequence[int] = [2020,2021,2022,2023,2024]

    LAKE = Path("datalake/lake")

    def run(years:int|Sequence[int]):
        if(isinstance(years, int)):
            years = [years]
        print(f"# [bold]RUNNING FOR YEARS:[/] {years}")
        
        for year in years:
            print()
            print(f"# starting: [bold yellow]{year}[/]")
            resample_and_verify(
                LAKE, 
                source=SOURCE, 
                market=MARKET, 
                symbol=SYMBOL, 
                year=year
            )
            pause()

    run(years=YEARS) #, force=True)
