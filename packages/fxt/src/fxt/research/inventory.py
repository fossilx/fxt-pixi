'''
inventory

What every config hash under data/research means, read from the files.

    entries = config_inventory()                  # every stage
    entries = config_inventory(stage="events")
    for e in entries:
        e.config_hash, e.config_typeid, e.changed   # changed = values that differ from defaults
        e.series                                    # {"dukascopy/forex/EURJPY": (2020, ..., 2024)}

Each config folder is summarized from its files' metadata: the config itself
comes from the first file (write_table guarantees every file in a folder
holds the same config; that's re-checked here and reported as a problem
otherwise). Nothing is cached: the files are the source of truth.

This is the scan the experiment registry's `configs` / `artifacts` tables
will be filled from (ML pipeline spec §10).
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter
from pydantic_core import PydanticUndefined

from .models import ResearchMeta, registry
from .paths import Research, Stage

__all__ = ["ConfigEntry", "changed_from_defaults", "config_inventory"]


@dataclass(frozen=True)
class ConfigEntry:
    stage: Stage
    config_hash: str
    config_typeid: str
    config: dict[str, Any]
    changed: dict[str, Any]                         # values that differ from the class defaults
    input_hashes: dict[str, str]
    series: dict[str, tuple[int | None, ...]]       # "source/market/symbol" -> years (None = not yearly)
    files: int
    rows: int
    created_first: datetime
    created_last: datetime
    code_versions: tuple[str, ...]
    known_class: bool                               # is config_typeid registered in this code?
    problems: tuple[str, ...] = field(default=())

    @property
    def label(self) -> str:
        """ e.g. "CusumEventsConfig@1 h=2.5" ("defaults" if nothing changed). """
        if not self.changed:
            return f"{self.config_typeid} defaults"
        return f"{self.config_typeid} " + " ".join(f"{k}={v}" for k, v in self.changed.items())
#


def changed_from_defaults(config_typeid: str, config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """ ({field: value} for every stored value that isn't the class default, class_is_known).

        Fields without a default (e.g. events_hash) always count as changed. If the
        class isn't registered in this code (renamed, removed), everything counts.
    """
    if not registry.has_model(config_typeid):
        return dict(config), False
    cls = registry.get_model(config_typeid)
    out: dict[str, Any] = {}
    for name, value in config.items():
        info = cls.model_fields.get(name)
        if info is None or (info.default is PydanticUndefined and info.default_factory is None):
            out[name] = value
            continue
        default = info.get_default(call_default_factory=True)
        if TypeAdapter(info.annotation).dump_python(default, mode="json") != value:
            out[name] = value
    return out, True
#


def config_inventory(research: Research | None = None, *, stage: Stage | str | None = None,
                     config_hash: str | None = None) -> list[ConfigEntry]:
    """ One entry per config folder, sorted by stage then first-created time. """
    if research is None:
        from fxt.services import get_research
        research = get_research()
    from .store import read_meta

    stages = [Stage(stage)] if stage else list(Stage)
    out: list[ConfigEntry] = []
    for st in stages:
        hashes = [config_hash] if config_hash else research.configs(st)
        for h in hashes:
            found = research.scan(st, config=h)
            if not found:
                continue
            metas: list[ResearchMeta] = []
            problems: list[str] = []
            for _, p in found:
                try:
                    metas.append(read_meta(p))
                except Exception as e:                          # unreadable / tampered file
                    problems.append(f"{p.name}: {e.__class__.__name__}: {str(e).splitlines()[0]}")
            if not metas:
                continue
            first = metas[0]
            if any(not m.same_config(first) for m in metas[1:]):
                problems.append("files in this folder hold different configs")

            series: dict[str, list[int | None]] = {}
            for m in metas:
                series.setdefault(str(m.dataset), []).append(m.year)
            changed, known = changed_from_defaults(first.config_typeid, first.config)
            out.append(ConfigEntry(
                stage=st,
                config_hash=h,
                config_typeid=first.config_typeid,
                config=dict(first.config),
                changed=changed,
                input_hashes=dict(first.input_hashes),
                series={k: tuple(sorted(v, key=lambda y: (y is None, y or 0)))
                        for k, v in sorted(series.items())},
                files=len(metas),
                rows=sum(m.rows for m in metas),
                created_first=min(m.created_at for m in metas),
                created_last=max(m.created_at for m in metas),
                code_versions=tuple(sorted({m.code_version for m in metas if m.code_version})),
                known_class=known,
                problems=tuple(problems),
            ))
    out.sort(key=lambda e: (list(Stage).index(e.stage), e.created_first))
    return out
#-
