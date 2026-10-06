#!/usr/bin/env bash
# Read-only. Does not stop mining, alter clocks, or print HiveOS credentials.
set -u
python3 - <<'PY'
import json, platform, subprocess
out={'kernel':platform.release(),'python':platform.python_version()}
for key,cmd in [
 ('gpu',['nvidia-smi','--query-gpu=index,name,driver_version,compute_cap,memory.total,memory.free,power.draw','--format=csv,noheader']),
 ('libc',['getconf','GNU_LIBC_VERSION']),
 ('memory',['free','-m'])]:
 try:
  r=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
  out[key]=r.stdout.strip() or r.stderr.strip()
 except (OSError,subprocess.SubprocessError) as e:out[key]=str(e)
print(json.dumps(out,indent=2))
PY
