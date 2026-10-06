#!/usr/bin/env bash
set -euo pipefail
prl_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
prl_build=${1:-/tmp/prl3060-host-tests}
# This build lacks CUDA and cannot mine. Even if cargo happens to be installed,
# the integration checks below use only localhost and do not launch the miner.
cmake -S "$prl_root/engine" -B "$prl_build" -DCP_ENABLE_CPU=ON -DCP_ENABLE_CUDA=OFF \
  -DCP_ENABLE_OPENCL=OFF -DPRL_ALLOW_PROOF_STUB_TEST_ONLY=ON -DCMAKE_BUILD_TYPE=Release
cmake --build "$prl_build" -j 2
python3 - "$prl_root" "$prl_build" <<'PY'
from pathlib import Path
import json,subprocess,sys
root,build=map(Path,sys.argv[1:])
objects=[str(p) for p in (build/'CMakeFiles/cppminer.dir').rglob('*.o') if p.name!='main.cpp.o']
# This harness links the production network code and its ordinary host dependencies.
cmd=['g++','-std=c++17','-O2','-pthread','-fopenmp','-I'+str(root/'engine/include'),'-I'+str(root/'engine/third_party/json'),str(root/'tests/test_pool.cpp'),*objects]
proof=root/'engine/rust/cp-proof-ffi/target/release/libcp_proof_ffi.a'
if proof.exists():cmd.extend([str(proof),'-ldl','-lm'])
cmd.extend(['-o',str(build/'test_pool')]);subprocess.run(cmd,check=True)
r=subprocess.run([str(build/'test_pool')],check=True,capture_output=True,text=True,timeout=10)
print(r.stdout)
events=[json.loads(x[12:]) for x in r.stdout.splitlines() if x.startswith('[prl-event] ')]
shares=[x for x in events if x['type']=='share']
assert [(x['id'],x['accepted']) for x in shares]==[(2,False),(3,True)]
print('Response ID correlation: PASS')
PY
python3 "$prl_root/tests/test_runtime.py"
