'''
fxt.research

Everything under data/research: tables whose contents depend on a config
(features, events, labels, weights). See ML pipeline spec §3.

    paths.py    Stage, ResearchKey, Research (path builder + scanning)
    models/     StageConfig, ResearchMeta, and the research registry
    store.py    write_table / read_table, lineage helpers
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from .paths import RESEARCH_KEYS, Research, ResearchKey, ResearchPathNotFound, Stage

__all__ = ["RESEARCH_KEYS", "Research", "ResearchKey", "ResearchPathNotFound", "Stage"]
