#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
# stop pylance from being annoying by adding this to end of line:  # type: ignore
# https://rich.readthedocs.io/en/stable/appendix/colors.html

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
import polars as pl
import pyarrow.parquet as pq
import pytest


from fxt.writer import write_ticks_parquet


@pytest.fixture
def ticks_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "timestamp": [1, 2, 3],
            "bid": [1.1000, 1.1001, 1.1002],
            "ask": [1.1002, 1.1003, 1.1004],
        }
    )


@pytest.fixture
def parquet_path(tmp_path):
    return tmp_path / "out" / "EURUSD.parquet"


@pytest.mark.parametrize(
    "metadata",
    [
        {"symbol": "EURUSD", "source": "dukascopy"},
        {"symbol": "GBPUSD", "source": "dukascopy", "version": "1"},
    ],
)
def test_write_ticks_parquet_creates_file_with_metadata(
    ticks_df, parquet_path, metadata
):
    result = write_ticks_parquet(ticks_df, parquet_path, metadata)

    # 1. File was created
    assert result == parquet_path
    assert parquet_path.exists()
    assert parquet_path.stat().st_size > 0

    # 2. Metadata is correct (pyarrow returns bytes keys/values)
    raw = pq.read_schema(parquet_path).metadata
    stored = {k.decode(): v.decode() for k, v in raw.items()}
    for key, value in metadata.items():
        assert stored[key] == value

    # 3. Data round-trips intact
    assert pl.read_parquet(parquet_path).equals(ticks_df)


def test_write_ticks_parquet_creates_missing_parent_dir(ticks_df, parquet_path):
    assert not parquet_path.parent.exists()

    write_ticks_parquet(ticks_df, parquet_path, {"symbol": "EURUSD"})

    assert parquet_path.exists()