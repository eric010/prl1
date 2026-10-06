#!/usr/bin/env bash
set -euo pipefail
prl_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$prl_dir"
exec python3 -u "$prl_dir/runner.py" --config "${CUSTOM_CONFIG_FILENAME:-$prl_dir/config.json}"
