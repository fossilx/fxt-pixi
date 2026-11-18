""" fxt.lake.derived.bars: the bar-building algorithm. """
from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl
import pytest

from fxt.lake.derived import bars as B

quiet = lambda msg: None    # noqa: E731  (log sink for builds)


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def duckdb_1min(src: Path, dst: Path) -> None:
    """ Independent reference: the original, verified DuckDB 1MIN builder.
        Ties on dtime break by file position (file_row_number).
    """
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(f"""COPY (
        WITH t AS (
            SELECT dtime, struct_pack(t := dtime, n := file_row_number) AS k,
                   bidPrice AS b, askPrice AS a, (bidPrice + askPrice) / 2 AS m,
                   bidVolume AS bv, askVolume AS av
            FROM read_parquet('{src}', hive_partitioning=false, file_row_number=true))
        SELECT time_bucket(INTERVAL 1 MINUTE, dtime) AS time,
            arg_min(b, k) AS bid_open, max(b) AS bid_high, min(b) AS bid_low, arg_max(b, k) AS bid_close,
            arg_min(a, k) AS ask_open, max(a) AS ask_high, min(a) AS ask_low, arg_max(a, k) AS ask_close,
            arg_min(m, k) AS mid_open, max(m) AS mid_high, min(m) AS mid_low, arg_max(m, k) AS mid_close,
            sum(bv) AS bid_volume, sum(av) AS ask_volume, count(*)::UINTEGER AS tick_count,
            avg(a - b) AS spread_mean, min(a - b) AS spread_min, max(a - b) AS spread_max
        FROM t GROUP BY 1 ORDER BY 1
    ) TO '{dst}' (FORMAT parquet)""")
    con.close()


def mismatches(a: Path, b: Path, rel: float = 0.0, skip: tuple[str, ...] = ()) -> dict[str, int]:
    """ Per-column count of bars that differ (full outer join on the bar instant).
        rel=0 means bit-exact. Missing bars on either side count under '_unmatched'.
    """
    def load(p: Path) -> pl.DataFrame:
        df = pl.read_parquet(p, hive_partitioning=False)
        t = pl.col(B.TIME_COL).dt.cast_time_unit("us")
        if df[B.TIME_COL].dtype.time_zone:    #type: ignore
            t = t.dt.convert_time_zone("UTC").dt.replace_time_zone(None)
        return df.with_columns(t)
    A, R = load(a), load(b)
    j = A.join(R, on=B.TIME_COL, how="full", coalesce=True, suffix="_ref")
    out = {"_unmatched": j.filter(pl.any_horizontal(pl.all().is_null())).height}
    for c in A.columns:
        if c == B.TIME_COL or c in skip:
            continue
        x, y = pl.col(c).cast(pl.Float64), pl.col(f"{c}_ref").cast(pl.Float64)
        tol = rel * pl.max_horizontal(x.abs(), y.abs(), pl.lit(1.0))
        out[c] = j.filter((x - y).abs() > tol).height
    return {k: v for k, v in out.items() if v}


VOLUMES = ("bid_volume", "ask_volume")


#!================================================================================(80)
#! correctness against the reference
#!--------------------------------------------------------------------------------(80)
def test_ticks_to_1min_matches_duckdb_reference(built, tmp_path):
    ref = tmp_path / "ref.parquet"
    duckdb_1min(built.raw, ref)
    # prices, counts, spreads: bit-exact
    assert mismatches(built.m1, ref, rel=0, skip=VOLUMES) == {}
    # volume sums: same values, different float summation order -> last-bit differences only
    assert mismatches(built.m1, ref, rel=1e-12) == {}

def test_output_schema_is_pinned(built):
    for p in (built.m1, built.h1):
        assert list(pl.read_parquet_schema(p).items()) == list(B.BAR_SCHEMA.items())

def test_bars_are_sparse_sorted_and_aligned(built, ticks):
    bars = pl.read_parquet(built.m1, hive_partitioning=False)
    t = bars[B.TIME_COL]
    assert t.is_sorted() and t.n_unique() == bars.height
    assert (t.dt.truncate("1m") == t).all()
    assert (t.dt.weekday() <= 5).all()                       # no bars on weekends: empty windows are skipped
    expected = ticks["dtime"].dt.truncate("1m").n_unique()
    assert bars.height == expected                           # one bar per minute that had ticks, no more
    assert bars["tick_count"].sum() == ticks.height


#!================================================================================(80)
#! resampling
#!--------------------------------------------------------------------------------(80)
@pytest.mark.parametrize("target, paths", [
    ("1HOUR", [("TICK", "1MIN"), ("1MIN", "1HOUR")]),
    ("1HOUR", [("TICK", "15MIN"), ("15MIN", "1HOUR")]),
    ("1HOUR", [("TICK", "5MIN"), ("5MIN", "15MIN"), ("15MIN", "1HOUR")]),
    ("15MIN", [("TICK", "5MIN"), ("5MIN", "15MIN")]),
])
def test_resampling_composes(built, tmp_path, target, paths):
    """ Building via intermediate widths gives the same bars as building directly from ticks. """
    direct = tmp_path / "direct.parquet"
    B.build_bars(built.raw, direct, source_interval="TICK", interval=target, log=quiet)
    src = built.raw
    for i, (s_iv, t_iv) in enumerate(paths):
        dst = tmp_path / f"step{i}_{t_iv}.parquet"
        B.build_bars(src, dst, source_interval=s_iv, interval=t_iv, log=quiet)
        src = dst
    assert mismatches(src, direct, rel=1e-12) == {}

def test_resampled_spread_mean_is_tick_weighted(built, ticks):
    """ 1HOUR spread_mean == mean spread over that hour's ticks (not a mean of minute means). """
    want = (ticks.with_columns((pl.col("askPrice") - pl.col("bidPrice")).alias("s"),
                               pl.col("dtime").dt.truncate("1h").alias(B.TIME_COL))
                 .group_by(B.TIME_COL).agg(pl.col("s").mean().alias("want"))
                 .with_columns(pl.col(B.TIME_COL).dt.cast_time_unit("us")))
    got = pl.read_parquet(built.h1, hive_partitioning=False).join(want, on=B.TIME_COL)
    assert got.height == want.height
    assert ((got["spread_mean"] - got["want"]).abs() <= 1e-12).all()

@pytest.mark.parametrize("source, target", [
    ("1HOUR", "1MIN"),     # finer than source
    ("1MIN",  "1MIN"),     # same width
    ("TICK",  "1DAY"),     # not registered (daily needs a session close)
    ("TICK",  "7MIN"),
])
def test_invalid_interval_combinations_are_refused(built, tmp_path, source, target):
    with pytest.raises(ValueError):
        B.build_bars(built.m1, tmp_path / "x.parquet", source_interval=source, interval=target, log=quiet)


#!================================================================================(80)
#! input handling
#!--------------------------------------------------------------------------------(80)
def test_unsorted_input_falls_back_to_stable_sort(ticks, tmp_path):
    """ Out-of-order input (pre-checks bypassed) is sorted, ties keep file order: same rule as
        the DuckDB reference's file_row_number, so the reference on the same file must match.
    """
    src = tmp_path / "unsorted.parquet"
    ticks.slice(0, 1000).reverse().vstack(ticks.slice(1000)).write_parquet(src)
    msgs: list[str] = []
    r = B.build_bars(src, tmp_path / "bars.parquet", source_interval="TICK", interval="1MIN", log=msgs.append)
    assert r.sorted_input is False
    assert any("not in time order" in m for m in msgs)
    ref = tmp_path / "ref.parquet"
    duckdb_1min(src, ref)
    assert mismatches(tmp_path / "bars.parquet", ref, rel=1e-12) == {}

def test_sorted_input_is_reported_as_sorted(built, tmp_path):
    r = B.build_bars(built.raw, tmp_path / "bars.parquet", source_interval="TICK", interval="1MIN", log=quiet)
    assert r.sorted_input is True

@pytest.mark.parametrize("tz", ["UTC", "Europe/London", "America/New_York"])
def test_timezone_aware_input_gives_same_instants(built, ticks, tmp_path, tz):
    src = tmp_path / "tz.parquet"
    ticks.with_columns(pl.col("dtime").dt.replace_time_zone("UTC").dt.convert_time_zone(tz)).write_parquet(src)
    dst = tmp_path / "bars.parquet"
    B.build_bars(src, dst, source_interval="TICK", interval="1MIN", log=quiet)
    assert pl.read_parquet_schema(dst)[B.TIME_COL] == pl.Datetime("us", "UTC")
    assert mismatches(dst, built.m1, rel=0) == {}

def test_same_millisecond_ties_use_file_order(tmp_path):
    """ Three ticks in the same millisecond: open is the first in the file, close the last. """
    t = pl.datetime(2014, 1, 6, 10, 0, 0, 500, time_unit="ms")
    df = pl.DataFrame({
        "bidPrice": [1.0, 3.0, 2.0], "askPrice": [1.1, 3.1, 2.1],
        "bidVolume": [1.0, 1.0, 1.0], "askVolume": [1.0, 1.0, 1.0],
    }).with_columns(dtime=t).select("dtime", pl.exclude("dtime"))
    src, dst = tmp_path / "ties.parquet", tmp_path / "bars.parquet"
    df.write_parquet(src)
    B.build_bars(src, dst, source_interval="TICK", interval="1MIN", log=quiet)
    bar = pl.read_parquet(dst).row(0, named=True)
    assert (bar["bid_open"], bar["bid_high"], bar["bid_low"], bar["bid_close"]) == (1.0, 3.0, 1.0, 2.0)
    assert bar["tick_count"] == 3


#!================================================================================(80)
#! file handling
#!--------------------------------------------------------------------------------(80)
def test_write_is_atomic_and_leaves_no_temp_file(built, tmp_path):
    dst = tmp_path / "sub" / "bars.parquet"            # parent created on demand
    B.build_bars(built.raw, dst, source_interval="TICK", interval="1MIN", log=quiet)
    assert dst.exists()
    assert list(dst.parent.iterdir()) == [dst]

def test_failed_build_keeps_existing_output(built, tmp_path):
    dst = tmp_path / "bars.parquet"
    dst.write_bytes(b"previous good file")
    bad = tmp_path / "bad.parquet"
    pl.DataFrame({"dtime": [1, 2]}).write_parquet(bad)   # missing price columns
    with pytest.raises(Exception):
        B.build_bars(bad, dst, source_interval="TICK", interval="1MIN", log=quiet)
    assert dst.read_bytes() == b"previous good file"

def test_build_result_describes_the_build(built, tmp_path):
    r = B.build_bars(built.m1, tmp_path / "h.parquet", source_interval="1MIN", interval="1HOUR", log=quiet)
    assert (r.transform, r.version) == B.RESAMPLE_BARS
    assert r.params == {"every": "1h"}
    assert r.rows == pl.read_parquet(tmp_path / "h.parquet").height


#!================================================================================(80)
#! performance (opt-in: pytest -m slow)
#!--------------------------------------------------------------------------------(80)
@pytest.mark.slow
def test_large_year_streams_in_bounded_memory(tmp_path, tick_factory):
    """ A heavy year (~25M ticks; EURJPY 2024 has ~54M) must build without loading the whole
        file. Peak memory is measured in a fresh subprocess via VmHWM: unlike ru_maxrss, it is
        reset by exec, so the parent's memory (e.g. from generating the data) doesn't leak in.
    """
    import subprocess, sys, textwrap
    src = tmp_path / "big.parquet"
    ticks = tick_factory(n=25_000_000, seed=11, start="2014-01-01", mean_gap_ms=1000)
    ticks = ticks.filter(pl.col("dtime").dt.year() == 2014)
    n_ticks = ticks.height
    ticks.write_parquet(src)
    del ticks
    code = textwrap.dedent(f"""
        import re, time
        from pathlib import Path
        from fxt.lake.derived.bars import build_bars
        t = time.perf_counter()
        build_bars(Path({str(src)!r}), Path({str(tmp_path / 'bars.parquet')!r}),
                   source_interval="TICK", interval="1MIN", log=lambda m: None)
        hwm_kb = int(re.search(r"VmHWM:\\s+(\\d+)", open("/proc/self/status").read()).group(1))
        print(time.perf_counter() - t, hwm_kb / 1024)
    """)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    secs, peak_mb = map(float, out.stdout.split())
    print(f"{n_ticks:,} ticks: {secs:.1f}s, peak {peak_mb:.0f} MB")
    assert n_ticks > 15_000_000                      # guard against the test silently shrinking
    assert peak_mb < 1500, f"peak RSS {peak_mb:.0f} MB: streaming path may have regressed"