#!/usr/bin/env bash
miner_config_gen() {
  local prl_dir
  prl_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
  CUSTOM_TEMPLATE="${CUSTOM_TEMPLATE:-}" CUSTOM_URL="${CUSTOM_URL:-stratum+tcp://prl.kryptex.network:7048}" \
  CUSTOM_PASS="${CUSTOM_PASS:-x}" CUSTOM_USER_CONFIG="${CUSTOM_USER_CONFIG:-}" \
  WORKER_NAME="${WORKER_NAME:-3060tix4}" CUSTOM_CONFIG_FILENAME="${CUSTOM_CONFIG_FILENAME:-$prl_dir/config.json}" \
  python3 "$prl_dir/configure.py"
}
miner_config_echo() { cat "${CUSTOM_CONFIG_FILENAME}"; }
