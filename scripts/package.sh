#!/usr/bin/env bash
set -euo pipefail
prl_binary=${1:?Usage: package.sh COMPILED_BINARY OUTPUT_DIR}
prl_out=${2:?Output directory required}
prl_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ -x "$prl_binary" ]] || { echo 'Missing compiled engine' >&2; exit 1; }
# --help is not enough to prove CUDA support. Inspect its built-backends line.
prl_help=$("$prl_binary" --help)
[[ "$prl_help" == *"cuda"* && "$prl_help" == *"cublas-period"* ]] || { echo 'Engine lacks CUDA/cuBLAS support' >&2; exit 1; }
if strings "$prl_binary" | grep -F 'HOST TEST BUILD ONLY' >/dev/null; then
  echo 'Refusing to package a host test build without proofs' >&2; exit 1
fi
mkdir -p "$prl_out"
prl_stage=$(mktemp -d)
trap 'rm -rf -- "$prl_stage"' EXIT
prl_dest="$prl_stage/prl3060-kryptex"
mkdir -p "$prl_dest/lib" "$prl_dest/licenses"
cp "$prl_root"/hiveos/*.py "$prl_root"/hiveos/*.sh "$prl_root"/hiveos/*.conf "$prl_dest/"
cp "$prl_root/hiveos/config.example.json" "$prl_dest/config.example.json"
cp "$prl_binary" "$prl_dest/prl3060-engine"
strip --strip-unneeded "$prl_dest/prl3060-engine"
cp "$prl_root/README-PT.md" "$prl_dest/"
cp "$prl_root/engine/LICENSE" "$prl_dest/licenses/CPPminer-MIT.txt"
cp "$prl_root/LICENSE" "$prl_dest/licenses/PRL3060-MIT.txt"
[[ ! -d "$prl_root/dependency-notices" ]] || cp -a "$prl_root/dependency-notices" "$prl_dest/licenses/"
cp "$prl_root/UPSTREAM.txt" "$prl_dest/"
# Include all dependency notices from the source, preserving their paths.
(cd "$prl_root/engine" && tar -cf - $(find third_party -type f -iname '*license*' -print)) | (cd "$prl_dest/licenses" && tar -xf -)
# Bundle CUDA shared runtimes, but never libcuda.so (comes from the rig driver).
# cuBLASLt is also needed even when it is loaded indirectly.
while IFS= read -r prl_lib; do
  [[ -f "$prl_lib" ]] && cp -L "$prl_lib" "$prl_dest/lib/"
done < <(ldd "$prl_binary" | awk '/libcudart|libcublas|libgomp|libstdc\+\+|libgcc_s/ {print $3}')
for prl_name in libcublas.so.12 libcublasLt.so.12 libcudart.so.12; do
  prl_path=$(find /usr/local/cuda/targets/x86_64-linux/lib -maxdepth 1 -name "$prl_name" -print -quit)
  [[ -n "$prl_path" ]] || { echo "Missing CUDA runtime: $prl_name" >&2; exit 1; }
  cp -L "$prl_path" "$prl_dest/lib/$prl_name"
done
for prl_notice in /usr/local/cuda/EULA.txt /usr/local/cuda/doc/EULA.txt /usr/local/cuda/doc/CUDA_Toolkit_Release_Notes.txt; do
  [[ ! -f "$prl_notice" ]] || cp "$prl_notice" "$prl_dest/licenses/"
done
chmod +x "$prl_dest"/*.sh "$prl_dest/prl3060-engine"
(cd "$prl_dest" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
tar -czf "$prl_out/prl3060-kryptex-0.1.1.tar.gz" -C "$prl_stage" prl3060-kryptex
