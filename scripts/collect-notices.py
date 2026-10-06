#!/usr/bin/env python3
"""Collect source notices for the locked Rust dependencies before packaging."""
import json
from pathlib import Path
import shutil
import subprocess
root=Path(__file__).resolve().parents[1]
manifest=root/'engine/rust/cp-proof-ffi/Cargo.toml'
data=json.loads(subprocess.check_output(['cargo','metadata','--locked','--format-version','1','--filter-platform','x86_64-unknown-linux-gnu','--manifest-path',str(manifest)],text=True))
dest=root/'dependency-notices';dest.mkdir(exist_ok=True)
lines=[]
for p in data['packages']:
    name=p['name']+'-'+p['version'];folder=Path(p['manifest_path']).parent
    lines.append(name+' | '+str(p.get('license'))+' | '+str(p.get('repository') or p.get('source') or 'vendored source'))
    out=dest/name;out.mkdir(exist_ok=True)
    for f in folder.iterdir():
        if f.is_file() and f.name.upper().startswith(('LICENSE','LICENCE','COPYING','NOTICE','UNLICENSE','README','CARGO.TOML')):
            shutil.copy2(f,out/f.name)
    if p.get('license_file'):
        f=folder/p['license_file']
        if f.is_file():shutil.copy2(f,out/f.name)
(dest/'DEPENDENCIES.txt').write_text('\n'.join(lines)+'\n')
