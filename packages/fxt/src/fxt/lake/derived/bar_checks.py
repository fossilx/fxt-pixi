"""
Verification checks for lake files, ported from the original build_1m_bars
script (verify_placement / verify_raw_ticks / verify_bars) to LakePicker Checks.

    pre_checks = [placement("src"), raw_tick_checks()]      # gate the build
    checks     = [placement("dst"), bar_checks("1MIN")]     # verify the output

Bar checks are source-aware: they reconcile bars against whatever ctx.src is,
raw ticks (1MIN bars) or finer bars (1HOUR from 1MIN), so the same list works
for every bar interval in fxt.lake.derived.bars.INTERVALS.

Schemas (from the original builder):
    ticks: dtime, bidPrice, askPrice, bidVolume, askVolume
    bars:  time, {bid,ask,mid}_{open,high,low,close}, bid_volume, ask_volume,
           tick_count, spread_mean, spread_min, spread_max
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import duckdb

from fxt.lake.paths import PartitionKey
from fxt.core.checks import Check, CheckResult, Status
from fxt.lake.derived.bars import TICK_TIME_COL, TIME_COL, get_interval
from fxt.lake.jobs import JobContext

Target = Literal["src", "dst"]

SERIES = ("bid", "ask", "mid")
OHLC = ("open", "high", "low", "close")
PRICE_TOL = 1e-12        # prices are copied, not computed, so they should match exactly
REL_TOL = 1e-9           # float sums: summation order changes the low bits
DUP_TICK_THRESHOLD = 1e-6


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def _con(ctx: JobContext) -> duckdb.DuckDBPyConnection:
    """ One connection per job, shared by every check via ctx.cache. """
    if "duckdb" not in ctx.cache:
        con = duckdb.connect()
        con.execute("SET TimeZone = 'UTC'")
        ctx.cache["duckdb"] = con
    return ctx.cache["duckdb"]

def scan(path: Path) -> str:
    """ file_row_number makes "file order" explicit, so ties on time break deterministically. """
    return f"read_parquet('{path}', hive_partitioning=false, file_row_number=true)"

def _scalar(ctx: JobContext, sql: str):
    return _con(ctx).execute(sql).fetchone()[0]

def _row(ctx: JobContext, sql: str) -> tuple:
    return _con(ctx).execute(sql).fetchone()

def _count(ctx: JobContext, path: Path, where: str) -> int:
    return _scalar(ctx, f"SELECT count(*) FROM {scan(path)} WHERE {where}")

def _close(a, b, rel: float = REL_TOL) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= rel * max(abs(a), abs(b), 1.0)

def _path(ctx: JobContext, target: Target) -> Path:
    p = ctx.src if target == "src" else ctx.dst
    if p is None or not p.exists():
        raise FileNotFoundError(f"{target} missing: {p}")
    return p

def _key(path: Path) -> PartitionKey:
    return PartitionKey.from_path(path)

def _is_ticks(path: Path) -> bool:
    return _key(path).interval == "TICK"

def _time_col(path: Path) -> str:
    return TICK_TIME_COL if _is_ticks(path) else TIME_COL

def _bucket(path: Path) -> str:
    """ duckdb INTERVAL literal for the file's bar width, e.g. '60 SECOND' """
    return f"{get_interval(_key(path).interval).seconds} SECOND"


def source_aggregates(src: Path) -> dict[str, str]:
    """ SQL aggregates over the *source* rows of one bar, keyed by bar column.
        This is what lets the reconciliation checks work for any bar interval.
        Uses ordered first()/last() rather than the builders' arg_min/arg_max, so a
        recompute exercises a different code path than the build.
    """
    if _is_ticks(src):
        k = f"{TICK_TIME_COL}, file_row_number"
        px = {"bid": "bidPrice", "ask": "askPrice", "mid": "(bidPrice + askPrice) / 2"}
        agg = {
            "tick_count": "count(*)",
            "bid_volume": "sum(bidVolume)", "ask_volume": "sum(askVolume)",
            "spread_min": "min(askPrice - bidPrice)", "spread_max": "max(askPrice - bidPrice)",
        }
        for s, e in px.items():
            agg |= {f"{s}_open": f"first({e} ORDER BY {k})", f"{s}_high": f"max({e})",
                    f"{s}_low":  f"min({e})",            f"{s}_close": f"last({e} ORDER BY {k})"}
    else:
        k = f"{TIME_COL}, file_row_number"
        agg = {
            "tick_count": "sum(tick_count)",
            "bid_volume": "sum(bid_volume)", "ask_volume": "sum(ask_volume)",
            "spread_min": "min(spread_min)", "spread_max": "max(spread_max)",
        }
        for s in SERIES:
            agg |= {f"{s}_open": f"first({s}_open ORDER BY {k})", f"{s}_high": f"max({s}_high)",
                    f"{s}_low":  f"min({s}_low)",              f"{s}_close": f"last({s}_close ORDER BY {k})"}
    return agg

PRICE_COLS  = [f"{s}_{x}" for s in SERIES for x in OHLC] + ["spread_min", "spread_max"]
VOLUME_COLS = ["bid_volume", "ask_volume"]
RECOMPUTE_COLS = PRICE_COLS + VOLUME_COLS + ["tick_count"]

def _mismatch_sql(a: str = "p", b: str = "ref") -> str:
    return " OR ".join(
        [f"abs({a}.{c} - {b}.{c}) > {PRICE_TOL}" for c in PRICE_COLS]
        + [f"abs({a}.{c} - {b}.{c}) > {REL_TOL} * greatest(abs({a}.{c}), abs({b}.{c}), 1)"
           for c in VOLUME_COLS]
        + [f"{a}.tick_count != {b}.tick_count"])


#!================================================================================(80)
#! placement (any file)
#!--------------------------------------------------------------------------------(80)
def placement(target: Target, group: str | None = None) -> list[Check]:
    """ Folder values must agree with the file's name and contents. """
    group = group or ("raw" if target == "src" else "bars")

    def filename(ctx: JobContext):
        p = _path(ctx, target)
        want = _key(p).filename
        return p.name == want, "" if p.name == want else f"expected {want}"

    def in_year(ctx: JobContext):
        p = _path(ctx, target)
        col = _time_col(p)
        # years + text computed in SQL: works for TIMESTAMP and TIMESTAMPTZ alike (the session
        # is UTC) and avoids handing tz-aware values to Python, which would need pytz
        ylo, yhi, lo, hi = _row(ctx, f"""SELECT year(min({col})), year(max({col})),
                                                min({col})::VARCHAR, max({col})::VARCHAR FROM {scan(p)}""")
        if ylo is None:
            return False, "file is empty"
        year = _key(p).year
        return ylo == year and yhi == year, f"{lo} .. {hi}"

    return [
        Check("filename matches folders", filename, group=group),
        Check("timestamps within folder year", in_year, group=group),
    ]


#!================================================================================(80)
#! raw ticks (ctx.src)
#!--------------------------------------------------------------------------------(80)
def raw_tick_checks(dup_threshold: float = DUP_TICK_THRESHOLD) -> list[Check]:
    g = "raw"

    def has_rows(ctx):
        n = _scalar(ctx, f"SELECT count(*) FROM {scan(_path(ctx, 'src'))}")
        ctx.cache["raw_rows"] = n
        return CheckResult(status=Status.PASS if n else Status.FAIL, detail=f"{n:,} ticks", value=n)

    def no_nulls(ctx):
        n = _count(ctx, _path(ctx, "src"), "dtime IS NULL OR bidPrice IS NULL OR askPrice IS NULL")
        return n == 0, f"{n} rows"

    def positive(ctx):
        n = _count(ctx, _path(ctx, "src"), "bidPrice <= 0 OR askPrice <= 0")
        return n == 0, f"{n} rows"

    def not_crossed(ctx):
        n = _count(ctx, _path(ctx, "src"), "askPrice < bidPrice")
        return n == 0, f"{n} crossed"

    def sorted_(ctx):
        n = _scalar(ctx, f"""SELECT count(*) FROM (
            SELECT dtime < lag(dtime) OVER (ORDER BY file_row_number) AS bad
            FROM {scan(_path(ctx, 'src'))}) WHERE bad""")
        return n == 0, f"{n} out-of-order"

    def duplicates(ctx):
        total, n = _row(ctx, f"""SELECT count(*),
            count(*) - count(DISTINCT (dtime, bidPrice, askPrice, bidVolume, askVolume))
            FROM {scan(_path(ctx, 'src'))}""")
        if not total:
            return False, "file is empty"
        frac = n / total
        return CheckResult(status=Status.PASS if frac < dup_threshold else Status.FAIL,
                           detail=f"{n} duplicates ({frac:.1e} of rows)", value=frac)

    return [
        Check("has rows", has_rows, group=g),
        Check("no null prices/times", no_nulls, group=g),
        Check("prices positive", positive, group=g),
        Check("no crossed quotes", not_crossed, group=g),
        Check("dtime sorted in file order", sorted_, group=g),
        Check(f"duplicate ticks < {dup_threshold:.0e}", duplicates, group=g),
    ]


#!================================================================================(80)
#! bars (ctx.dst, reconciled against ctx.src)
#!--------------------------------------------------------------------------------(80)
def bar_checks(sample: int = 200, seed: int = 42, full: bool = True) -> list[Check]:
    g = "bars"
    dst = lambda ctx: _path(ctx, "dst")
    src = lambda ctx: _path(ctx, "src")

    # -- structure --------------------------------------------------------------
    def has_rows(ctx):
        n = _scalar(ctx, f"SELECT count(*) FROM {scan(dst(ctx))}")
        return CheckResult(status=Status.PASS if n else Status.FAIL, detail=f"{n:,} bars", value=n)

    def unique(ctx):
        n = _scalar(ctx, f"SELECT count(*) - count(DISTINCT {TIME_COL}) FROM {scan(dst(ctx))}")
        return n == 0, f"{n} dupes"

    def sorted_(ctx):
        n = _scalar(ctx, f"""SELECT count(*) FROM (
            SELECT {TIME_COL} < lag({TIME_COL}) OVER (ORDER BY file_row_number) AS bad
            FROM {scan(dst(ctx))}) WHERE bad""")
        return n == 0, f"{n} out-of-order"

    def aligned(ctx):
        p = dst(ctx)
        b = _bucket(p)
        n = _count(ctx, p, f"{TIME_COL} != time_bucket(INTERVAL {b}, {TIME_COL})")
        return n == 0, f"{n} off a {b.lower()} boundary"

    # -- per-bar consistency ----------------------------------------------------
    def ohlc(series: str):
        o, h, l, c = (f"{series}_{x}" for x in OHLC)
        def fn(ctx):
            n = _count(ctx, dst(ctx),
                       f"{l} > {h} OR {o} NOT BETWEEN {l} AND {h} OR {c} NOT BETWEEN {l} AND {h}")
            return n == 0, f"{n} bad bars"
        return Check(f"{series} OHLC consistent", fn, group=g)

    def mid_is_avg(ctx):
        n = _count(ctx, dst(ctx), " OR ".join(
            f"abs(mid_{x} - (bid_{x} + ask_{x}) / 2) > {PRICE_TOL}" for x in ("open", "close")))
        return n == 0, f"{n} bars"

    def tick_count_pos(ctx):
        n = _count(ctx, dst(ctx), "tick_count IS NULL OR tick_count <= 0")
        return n == 0, f"{n} bars"

    def spread_ok(ctx):
        n = _count(ctx, dst(ctx), f"""spread_min < 0 OR spread_min > spread_max
            OR spread_mean < spread_min - {PRICE_TOL} OR spread_mean > spread_max + {PRICE_TOL}""")
        return n == 0, f"{n} bars"

    # -- reconciliation with source ---------------------------------------------
    def tick_total(ctx):
        agg = source_aggregates(src(ctx))
        want, got = _row(ctx, f"""SELECT (SELECT {agg['tick_count']} FROM {scan(src(ctx))}),
                                         (SELECT sum(tick_count)    FROM {scan(dst(ctx))})""")
        return CheckResult(status=Status.PASS if want == got else Status.FAIL,
                           detail=f"{got:,} vs {want:,} in source", value=(got or 0) - (want or 0))

    def extremes(ctx):
        agg = source_aggregates(src(ctx))
        pairs = [(f"{s}_high", "max") for s in SERIES] + [(f"{s}_low", "min") for s in SERIES]
        sql = ", ".join(f"(SELECT {fn}({c}) FROM {scan(dst(ctx))}) - (SELECT {agg[c]} FROM {scan(src(ctx))})"
                        for c, fn in pairs)
        diffs = dict(zip((c for c, _ in pairs), _row(ctx, f"SELECT {sql}")))
        bad = {c: d for c, d in diffs.items() if d is None or abs(d) > PRICE_TOL}
        return not bad, "all 6 match" if not bad else ", ".join(f"{c} off {d}" for c, d in bad.items())

    def volumes(ctx):
        agg = source_aggregates(src(ctx))
        bb, ba, rb, ra = _row(ctx, f"""SELECT
            (SELECT sum(bid_volume) FROM {scan(dst(ctx))}), (SELECT sum(ask_volume) FROM {scan(dst(ctx))}),
            (SELECT {agg['bid_volume']} FROM {scan(src(ctx))}), (SELECT {agg['ask_volume']} FROM {scan(src(ctx))})""")
        ok = _close(bb, rb) and _close(ba, ra)
        return ok, f"bid {bb:.6g} vs {rb:.6g}; ask {ba:.6g} vs {ra:.6g}"

    def spot_check(ctx):
        """ Independently recompute a random sample of bars from the source (range join +
            ordered aggregates: a different code path from the builder's GROUP BY).
            MATERIALIZED + REPEATABLE: both references see the same sample, and a failure
            reproduces. LEFT JOIN so a bar with no source rows counts as a failure.
        """
        s, d = src(ctx), dst(ctx)
        agg = source_aggregates(s)
        tc, b = _time_col(s), _bucket(d)
        ref_select = ", ".join(f"{agg[c]} AS {c}" for c in RECOMPUTE_COLS)
        mismatch = _mismatch_sql()
        missing, bad, first_bad = _row(ctx, f"""
            WITH picks AS MATERIALIZED (
                SELECT * FROM {scan(d)} USING SAMPLE reservoir({sample} ROWS) REPEATABLE ({seed})),
            keys AS (SELECT {TIME_COL} AS bt FROM picks),
            ref AS (
                SELECT k.bt, {ref_select}
                FROM keys k JOIN {scan(s)} r ON r.{tc} >= k.bt AND r.{tc} < k.bt + INTERVAL {b}
                GROUP BY k.bt)
            SELECT count(*) FILTER (WHERE ref.bt IS NULL),
                   count(*) FILTER (WHERE ref.bt IS NOT NULL AND ({mismatch})),
                   (min(p.{TIME_COL}) FILTER (WHERE ref.bt IS NULL OR ({mismatch})))::VARCHAR
            FROM picks p LEFT JOIN ref ON p.{TIME_COL} = ref.bt""")
        ok = missing == 0 and bad == 0
        detail = f"{bad} mismatches, {missing} without source rows"
        if not ok:
            detail += f" (first: {first_bad})"
        return ok, detail

    def full_recompute(ctx):
        """ Rebuild every bar from the source (GROUP BY time_bucket with ordered first/last)
            and FULL OUTER JOIN against the file: catches wrong values in any bar, plus
            bars missing from or extra in the file. Costs about as much as a build.
        """
        s, d = src(ctx), dst(ctx)
        agg = source_aggregates(s)
        tc, b = _time_col(s), _bucket(d)
        ref_select = ", ".join(f"{agg[c]} AS {c}" for c in RECOMPUTE_COLS)
        mismatch = _mismatch_sql()
        extra, missing, bad, first_bad = _row(ctx, f"""
            WITH ref AS (
                SELECT time_bucket(INTERVAL {b}, {tc}) AS bt, {ref_select}
                FROM {scan(s)} GROUP BY 1)
            SELECT count(*) FILTER (WHERE ref.bt IS NULL),
                   count(*) FILTER (WHERE p.{TIME_COL} IS NULL),
                   count(*) FILTER (WHERE p.{TIME_COL} IS NOT NULL AND ref.bt IS NOT NULL AND ({mismatch})),
                   (min(coalesce(p.{TIME_COL}, ref.bt)) FILTER (
                       WHERE p.{TIME_COL} IS NULL OR ref.bt IS NULL OR ({mismatch})))::VARCHAR
            FROM {scan(d)} p FULL OUTER JOIN ref ON p.{TIME_COL} = ref.bt""")
        ok = extra == 0 and missing == 0 and bad == 0
        detail = f"{bad} mismatches, {missing} missing, {extra} extra"
        if not ok:
            detail += f" (first: {first_bad})"
        return CheckResult(status=Status.PASS if ok else Status.FAIL, detail=detail, value=bad + missing + extra)

    checks = [
        Check("has rows", has_rows, group=g),
        Check("time unique", unique, group=g),
        Check("time sorted", sorted_, group=g),
        Check("time aligned to interval", aligned, group=g),
        *(ohlc(s) for s in SERIES),
        Check("mid open/close = (bid+ask)/2", mid_is_avg, group=g),
        Check("tick_count > 0", tick_count_pos, group=g),
        Check("spread non-negative, mean in [min,max]", spread_ok, group=g),
        Check("tick_count reconciles with source", tick_total, group=g),
        Check("global highs/lows match source", extremes, group=g),
        Check("volume totals match source", volumes, group=g),
        Check(f"{sample}-bar range-join recompute", spot_check, group=g),
    ]
    if full:
        checks.append(Check("full recompute (every bar)", full_recompute, group=g))
    return checks