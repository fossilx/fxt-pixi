""" Pick a derived 1MIN year -> resample to 1HOUR bars, with verification. """
from pathlib import Path

from fxt.lake.paths import PartitionKey
from fxt.services import get_lake

from fxt.lake.derived import bar_checks as bc
from fxt.lake.derived.bars import build_bars
from fxt.lake.derived.meta import input_meta_checks, remember_build, stamp_bars
from fxt.lake.jobs import JobContext
from ..lake_picker import LakePicker

LAKE = get_lake()
OUT_INTERVAL = "1HOUR"


def out_path(key: PartitionKey) -> Path:
    out = key.replace(interval=OUT_INTERVAL)
    return LAKE.derived(**out.model_dump(), filename=out.filename, must_exist=False)


def build(ctx: JobContext) -> None:
    assert ctx.dst is not None
    ctx.log(f"src: {ctx.src.relative_to(LAKE.root)}")
    ctx.log(f"dst: {ctx.dst.relative_to(LAKE.root)}")
    # stamp_bars (on_report) writes BarsMeta after the post-checks have run
    remember_build(ctx, build_bars(ctx.src, ctx.dst, source_interval=ctx.key.interval, interval=OUT_INTERVAL, log=ctx.log))


# the 1MIN source was verified when it was built; placement is a cheap sanity check
PRE_CHECKS = [bc.placement("src", group="1MIN"), input_meta_checks()]
CHECKS     = [bc.placement("dst"), bc.bar_checks()]

if __name__ == "__main__":
    LakePicker(
        root=LAKE.derived(),
        filters={"interval": "1MIN"},
        action_label=f"Generate {OUT_INTERVAL} bars",
        action=build,
        out_path=out_path,
        pre_checks=PRE_CHECKS,
        checks=CHECKS,
        on_report=stamp_bars, #type: ignore
        lake=LAKE,
    ).run()