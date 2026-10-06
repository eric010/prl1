#!/usr/bin/env bash
prl_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
stats=$(python3 - "$prl_dir/stats.json" <<'PY'
import json,sys,time
try:
 s=json.load(open(sys.argv[1]))
 print(json.dumps(s['hive']) if time.time()-s['updated']<35 else 'null')
except (OSError,ValueError,KeyError): print('null')
PY
)
khs=$(python3 - "$stats" <<'PY'
import json,sys
try:
 s=json.loads(sys.argv[1]); print(sum(s['hs'])/1000)
except (ValueError,TypeError,KeyError): print(0)
PY
)
