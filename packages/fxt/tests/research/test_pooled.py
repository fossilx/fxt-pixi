"""
Pooled evaluation across symbols (spec §9.7): per-symbol folds, costs and metrics, one model.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from fxt.research import Research
from fxt.research.harness import PREDICTION_COLUMNS, evaluate, simulate
from fxt.research.harness.baselines import _find_control
from fxt.research.harness.evaluate import PER_SYMBOL_METRICS
from fxt.research.models import BacktestConfig, GBMMulticlassModelConfig, LogisticModelConfig, SizerConfig, TakeAllModelConfig
from fxt.research.registry import Registry

from .test_harness import CV, synth_dataset


@pytest.fixture(scope="module")
def pair():
    a = synth_dataset(seed=3, symbol="AAAJPY")
    b = synth_dataset(seed=4, symbol="BBBUSD", every=11)
    return a, b


def test_single_dataset_or_list_of_one_are_identical(pair):
    a, _ = pair
    r1 = evaluate(a, model=LogisticModelConfig(), cv=CV, registry=None)
    r2 = evaluate([a], model=LogisticModelConfig(), cv=CV, registry=None)
    assert r1.trades.equals(r2.trades) and r1.aggregate == r2.aggregate
    assert "n_symbols" not in r1.aggregate


def test_pooled_run(pair, tmp_path):
    a, b = pair
    rs = Research(root=tmp_path / "research")
    with Registry(tmp_path / "x.db") as reg:
        res = evaluate([b, a], model=LogisticModelConfig(), cv=CV, registry=reg, research=rs)
        run = reg.runs().row(0, named=True)
        assert json.loads(run["symbols"]) == ["AAAJPY", "BBBUSD"]               # sorted
        t = res.trades
        assert set(t["symbol"].unique()) == {"AAAJPY", "BBBUSD"}
        #! every test event of both symbols, out of fold, in the dev years only
        n_a = a.frame.filter(pl.col("t0").dt.year().is_between(2015, 2016)).height
        n_b = b.frame.filter(pl.col("t0").dt.year().is_between(2015, 2016)).height
        assert t.height <= n_a + n_b and t.filter(pl.col("symbol") == "AAAJPY").height > 0
        assert set(t["t0"].dt.year().unique()) == {2015, 2016}
        #! per-symbol metrics and one predictions file per symbol
        for s in ("AAAJPY", "BBBUSD"):
            for k in ("n_trades", "net_bp", "clf_auc", "dir_auc"):
                assert f"{s}.{k}" in res.aggregate
            assert res.aggregate[f"{s}.n_trades"] == t.filter(pl.col("symbol") == s).height
            p = pl.read_parquet(rs.root / "predictions" / f"run={res.run_id}" / f"{s}.parquet")
            assert p.columns == list(PREDICTION_COLUMNS) and set(p["symbol"]) == {s}
        assert res.aggregate["n_symbols"] == 2
        assert res.aggregate["n_trades"] == res.aggregate["AAAJPY.n_trades"] + res.aggregate["BBBUSD.n_trades"]
        logged = reg.metrics(res.run_id).filter(pl.col("fold").is_null())["name"].to_list()
        assert "BBBUSD.net_bp" in logged and set(PER_SYMBOL_METRICS) <= {n.split(".", 1)[1] for n in logged if "." in n}


def test_pooled_folds_are_per_symbol(pair):
    a, b = pair
    res = evaluate([a, b], model=TakeAllModelConfig(), cv=CV, registry=None)
    for row in res.folds.iter_rows(named=True):
        ra = evaluate(a, model=TakeAllModelConfig(), cv=CV, registry=None).folds.row(row["fold"], named=True)
        rb = evaluate(b, model=TakeAllModelConfig(), cv=CV, registry=None).folds.row(row["fold"], named=True)
        assert row["n_train"] == ra["n_train"] + rb["n_train"]
        assert row["n_test"] == ra["n_test"] + rb["n_test"]
        assert row["purged"] == ra["purged"] + rb["purged"]


def test_pooled_model_uses_both_symbols(pair):
    a, b = pair
    res = evaluate([a, b], model=GBMMulticlassModelConfig(min_data_in_leaf=20), sizer=SizerConfig(rule="expected_value"),
                   cv=CV, registry=None)
    assert res.aggregate["clf_auc"] > 0.7                                      # x drives the label in both
    assert res.trades["p_sl"].null_count() == 0


def test_pooled_datasets_must_match(pair):
    a, b = pair
    with pytest.raises(ValueError, match="one dataset per symbol"):
        evaluate([a, a], model=TakeAllModelConfig(), cv=CV, registry=None)
    other = type(b)(**{**b.__dict__, "hashes": {**b.hashes, "labels": "f" * 12}})
    with pytest.raises(ValueError, match="hashes"):
        evaluate([a, other], model=TakeAllModelConfig(), cv=CV, registry=None)


def test_position_cap_is_per_symbol():
    h = [datetime(2020, 1, 6, k, tzinfo=UTC) for k in range(10)]
    pred = pl.DataFrame({"symbol": ["A", "B", "A"], "t0": [h[0], h[1], h[2]], "t1": [h[5], h[5], h[5]],
                         "size": [1.0, 1.0, 1.0], "ret": [0.01] * 3, "cost": [0.0] * 3})
    out = simulate(pred, BacktestConfig(position_cap=1.0))
    assert out["size"].to_list() == [1.0, 1.0, 0.0]                           # B isn't blocked by A


def test_find_control_matches_symbols(tmp_path):
    with Registry(tmp_path / "x.db") as reg:
        cfgs = {"labels": "a" * 12}
        one = reg.start_run("s", ["EURJPY"], cfgs, cv_scheme="w", data_start="", data_end="", purpose="control")
        reg.finish_run(one, "done")
        assert _find_control(reg, cfgs, ["EURJPY"]) == one
        assert _find_control(reg, cfgs, ["EURJPY", "EURUSD"]) is None          # a pooled control is different
