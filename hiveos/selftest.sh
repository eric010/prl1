#!/usr/bin/env bash
# Run this only after stopping the existing miner on the selected GPU.
set -euo pipefail
prl_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export LD_LIBRARY_PATH="$prl_dir/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OMP_NUM_THREADS=1 RAYON_NUM_THREADS=1
mkdir -p "$prl_dir/run/selftest"
export PRL_WORKDIR="$prl_dir/run/selftest"
[[ -x "$prl_dir/prl3060-engine" ]] || { echo 'Falta o executável CUDA compilado.' >&2; exit 1; }
exec "$prl_dir/prl3060-engine" --backend cuda --devices "${1:-0}" --cublas-period \
  --step-major --row-period-batch 4 --period-batch 32 --mock --mock-diff 40 --verify
