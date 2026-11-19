#!/usr/bin/env bash
# Build the default research chain for one or more symbols, in dependency order,
# then index the results in the experiment registry.
#
#   pixi run research-chain EURJPY
#   pixi run research-chain EURJPY GBPJPY
#
# Steps (each uses the previous step's default config, so they form one chain):
#   1. features       baseline, trend, flow feature sets  (reads 1HOUR bars; flow reads 1MIN)
#   2. events-cusum   CUSUM h=3 events                    (reads 1HOUR bars)
#   3. touches        triple-barrier touch pass k=1 N=48  (reads events, 1HOUR + 1MIN bars, ticks for ties)
#   4. labels         side labels: follow and fade        (reads touches)
#   5. weights        sample weights for both side rules  (reads labels, 1HOUR bars)
#   6. registry sync  index data/research in data/experiments.db
#
# Stops at the first failure. Re-running rebuilds and overwrites every file of
# these configs (same hashes, same paths).
set -euo pipefail

if [ "$#" -eq 0 ]; then
    echo "usage: pixi run research-chain SYMBOL [SYMBOL ...]" >&2
    exit 2
fi

step() {
    echo
    echo "=== [$1/6] $2: $3"
    shift 3
    "$@"
}

start=$(date +%s)
step 1 features      "$*" python -m fxtapps.research.features.cli "$@"
step 2 events-cusum  "$*" python -m fxtapps.research.events_cusum.cli "$@"
step 3 touches       "$*" python -m fxtapps.research.touches.cli "$@"
step 4 labels        "$*" python -m fxtapps.research.labels.cli "$@"
step 5 weights       "$*" python -m fxtapps.research.weights.cli "$@"
step 6 registry      sync python -m fxtapps.research.registry.cli sync
echo
echo "=== done in $(( $(date +%s) - start ))s"
