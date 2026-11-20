"""
Cross-pair features (CrossFeaturesConfig, spec §4.4): each leg's currency in the other pairs.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from fxt.research import Research
from fxt.research.features import build_features, compute_cross, pair_z, to_wide
from fxt.research.models import CrossFeaturesConfig, split_pair

MON = datetime(2020, 1, 6, tzinfo=UTC)
CFG = CrossFeaturesConfig(horizons=(1, 4), vol_window=10, min_coverage=1.0)


def triangle(n: int = 300, seed: int = 0, drop_usdjpy: slice | None = None) -> dict[str, pl.DataFrame]:
    """ EURUSD and USDJPY random walks; EURJPY = their product (a consistent triangle). """
    rng = np.random.default_rng(seed)
    t = [MON + timedelta(hours=i) for i in range(n)]
    eu = 1.1 * np.exp(np.cumsum(rng.normal(0, 1e-3, n)))
    uj = 110 * np.exp(np.cumsum(rng.normal(0, 1e-3, n)))
    def df(x, keep=None):
        d = pl.DataFrame({"time": t, "mid_close": x}).with_columns(pl.col("time").cast(pl.Datetime("us", "UTC")))
        return d if keep is None else d.filter(~pl.int_range(pl.len()).is_between(keep.start, keep.stop - 1))
    return {"EURUSD": df(eu), "USDJPY": df(uj, drop_usdjpy), "EURJPY": df(eu * uj)}


def wide(bars, symbol, cfg=CFG):
    return to_wide(compute_cross(bars[symbol], cfg, symbol=symbol, peers=bars), cfg.names()).sort("bar_time")


def z(bars, symbol, cfg=CFG):
    return pair_z(bars[symbol], cfg).sort("bar_time")


def test_config():
    c = CrossFeaturesConfig()
    assert c.config_hash() == "cdc2ad9c21de"
    assert c.names()[:3] == ("base_str_4h", "base_str_24h", "base_str_120h")
    assert set(c.signed_names()) == {n for n in c.names() if not n.startswith("driver")}
    assert split_pair("eurjpy") == ("EUR", "JPY")
    with pytest.raises(ValueError):
        CrossFeaturesConfig(basket=("USDJPY", "EURJPY"))                          # must be sorted
    with pytest.raises(ValueError):
        split_pair("EURJP")


def test_eurjpy_legs_are_the_other_pairs():
    b = triangle()
    w = wide(b, "EURJPY").join(z(b, "EURUSD"), on="bar_time").join(
        z(b, "USDJPY").rename({"z1": "uj1", "z4": "uj4"}), on="bar_time").drop_nulls()
    assert w.height > 200
    #! EUR strength = EURUSD's z (EURJPY itself left out); JPY strength = -USDJPY's z
    assert np.allclose(w["base_str_4h"], w["z4"]) and np.allclose(w["quote_str_1h"], -w["uj1"])
    d = (w["base_str_4h"].abs() - w["quote_str_4h"].abs()) / (w["base_str_4h"].abs() + w["quote_str_4h"].abs())
    assert np.allclose(w["driver_4h"], d) and w["driver_4h"].is_between(-1, 1).all()


def test_usdjpy_uses_eur_pairs():
    b = triangle(seed=1)
    w = wide(b, "USDJPY").join(z(b, "EURUSD"), on="bar_time").join(
        z(b, "EURJPY").rename({"z1": "ej1", "z4": "ej4"}), on="bar_time").drop_nulls()
    #! USD is EURUSD's quote -> -z; JPY is EURJPY's quote -> -z
    assert np.allclose(w["base_str_4h"], -w["z4"]) and np.allclose(w["quote_str_4h"], -w["ej4"])


def test_currency_outside_the_basket_is_absent():
    b = triangle(seed=2)
    b["GBPJPY"] = b["EURJPY"].with_columns(pl.col("mid_close") * 1.2)
    long = compute_cross(b["GBPJPY"], CFG, symbol="GBPJPY", peers=b)
    names = set(long["name"].unique())
    assert not any(n.startswith(("base_str", "driver")) for n in names)   # no other GBP pair
    assert any(n.startswith("quote_str") for n in names)                                 # JPY: from all three


def test_missing_peer_hours_and_bars():
    b = triangle(seed=3, drop_usdjpy=slice(100, 110))
    w = wide(b, "EURJPY")
    gap = w.filter(pl.col("bar_time").is_between(MON + timedelta(hours=101), MON + timedelta(hours=110)))
    assert gap["quote_str_1h"].null_count() == gap.height and gap["base_str_1h"].null_count() == 0
    with pytest.raises(ValueError, match="need bars"):
        compute_cross(b["EURJPY"], CFG, symbol="EURJPY", peers={"EURUSD": b["EURUSD"]})


def test_point_in_time():
    b = triangle(seed=4)
    a = compute_cross(b["EURJPY"], CFG, symbol="EURJPY", peers=b)
    later = {k: v.with_columns(pl.when(pl.col("time") >= MON + timedelta(hours=200))
                               .then(pl.col("mid_close") * 1.05).otherwise(pl.col("mid_close")).alias("mid_close"))
             for k, v in b.items()}
    c = compute_cross(later["EURJPY"], CFG, symbol="EURJPY", peers=later)
    cut = MON + timedelta(hours=200)
    assert a.filter(pl.col("bar_time") <= cut).equals(c.filter(pl.col("bar_time") <= cut))


def test_build_reads_every_basket_pair(tmp_path, monkeypatch):
    import fxt.research.features.build as fb
    b = triangle(n=400, seed=5)
    calls = []
    def fake_load_bars(lake, *, source, market, symbol, interval, columns):
        calls.append(symbol)
        return b[symbol], [Path(f"/lake/{symbol}.parquet")]
    monkeypatch.setattr(fb, "load_bars", fake_load_bars)
    monkeypatch.setattr(fb, "file_ref", lambda p, **kw: None)
    class L:
        root = tmp_path
    res = build_features(CFG, source="dukascopy", market="forex", symbol="EURJPY", lake=L(),
                         research=Research(root=tmp_path / "r"), write=False)
    assert calls == ["EURJPY", "EURUSD", "USDJPY"]
    assert len(res.inputs) == 3
    assert set(res.features["name"].unique()) == set(CFG.names())
