#!/usr/bin/env python3
"""Reproducible Linux sm_86 build with an Ubuntu 22.04 sysroot, no GPU needed.
Requires Python 3.12+, curl, git, dpkg-deb, make and a recent CMake on PATH.
Downloads official CUDA/Rust/Ubuntu components and checks manifest SHA256 values.
All toolchains and intermediate build files stay in PRL_BUILD_CACHE (/tmp by default).
"""
import concurrent.futures as F
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess as S
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get('PRL_BUILD_CACHE', '/tmp/prl3060-rebuild'))
DOWNLOADS = CACHE/'downloads'
DOWNLOADS.mkdir(parents=True, exist_ok=True)

def run(args, **kwargs):
    return S.run([str(x) for x in args], check=True, **kwargs)

def fetch(url, name, digest=None):
    dest = DOWNLOADS/name
    if not dest.exists():
        run(['curl','-fLsS','--retry','2','--connect-timeout','30','--max-time','900',url,'-o',dest])
    if digest:
        h=hashlib.sha256()
        with dest.open('rb') as f:
            for b in iter(lambda:f.read(1048576),b''):h.update(b)
        if h.hexdigest()!=digest: raise RuntimeError('SHA256 mismatch: '+name)
    return dest

def archive_component(item):
    name,url,digest=item
    p=fetch(url,Path(url).name,digest)
    d=CACHE/'extract'/name;d.mkdir(parents=True,exist_ok=True)
    with tarfile.open(p) as t:t.extractall(d,filter='data')
    print('Verified and extracted: '+name,flush=True)
    return name,next(d.iterdir())

manifest=json.loads(fetch('https://developer.download.nvidia.com/compute/cuda/redist/redistrib_12.8.1.json','cuda.json').read_text())
rust=tomllib.loads(fetch('https://static.rust-lang.org/dist/channel-rust-1.90.0.toml','rust.toml').read_text())
items=[]
for name in ['cuda_nvcc','cuda_cudart','cuda_cccl','libcublas','cuda_cuobjdump']:
    c=manifest[name]['linux-x86_64']
    items.append((name,'https://developer.download.nvidia.com/compute/cuda/redist/'+c['relative_path'],c['sha256']))
for name in ['rustc','rust-std','cargo']:
    c=rust['pkg'][name]['target']['x86_64-unknown-linux-gnu']
    items.append((name,c['xz_url'],c['xz_hash']))
with F.ThreadPoolExecutor(max_workers=4) as ex:
    extracted=dict(ex.map(archive_component,items))
cuda=CACHE/'cuda';cuda.mkdir(exist_ok=True)
for name in ['cuda_nvcc','cuda_cudart','cuda_cccl','libcublas','cuda_cuobjdump']:
    shutil.copytree(extracted[name],cuda,dirs_exist_ok=True,symlinks=True)
if not (cuda/'lib64').exists():(cuda/'lib64').symlink_to('lib')
for name in ['rustc','rust-std','cargo']:
    run(['bash',extracted[name]/'install.sh','--prefix='+str(CACHE/'rust'),'--disable-ldconfig'],stdout=S.DEVNULL)

pkgfile=fetch('https://archive.ubuntu.com/ubuntu/dists/jammy-updates/main/binary-amd64/Packages.xz','ubuntu-packages.xz')
packages={}
for para in lzma.open(pkgfile,'rt').read().split('\n\n'):
    d=dict(line.split(': ',1) for line in para.splitlines() if line and line[0]!=' ' and ': ' in line)
    if 'Package' in d:packages[d['Package']]=d
names=['gcc-11','g++-11','cpp-11','gcc-11-base','libgcc-11-dev','libstdc++-11-dev','libc6','libc6-dev','libc-dev-bin','linux-libc-dev','libstdc++6','libgcc-s1','libgomp1','libcc1-0','libitm1','libatomic1','libasan6','liblsan0','libtsan0','libubsan1','libquadmath0']
def get_deb(name):
    d=packages[name]
    return fetch('https://archive.ubuntu.com/ubuntu/'+d['Filename'],name+'.deb',d['SHA256'])
sysroot=CACHE/'sysroot';sysroot.mkdir(exist_ok=True)
with F.ThreadPoolExecutor(max_workers=5) as ex:
    for p in ex.map(get_deb,names):run(['dpkg-deb','-x',p,sysroot])
(CACHE/'ubuntu-packages.json').write_text(json.dumps({n:packages[n] for n in names},indent=2))
wrappers=CACHE/'wrappers';wrappers.mkdir(exist_ok=True)
for name,cc in [('cc','gcc'),('cxx','g++')]:
    p=wrappers/name
    p.write_text('#!/bin/sh\nexec "'+str(sysroot/'usr/bin'/('x86_64-linux-gnu-'+cc+'-11'))+'" --sysroot="'+str(sysroot)+'" "$@"\n')
    p.chmod(0o755)
cutlass=ROOT/'engine/third_party/cutlass'
if not cutlass.exists():run(['git','clone','--depth','1','--branch','v2.11.0','https://github.com/NVIDIA/cutlass.git',cutlass])
sha=S.check_output(['git','-C',str(cutlass),'rev-parse','HEAD'],text=True).strip()
assert sha=='66d9cddc832c1cdc2b30a8755274f7f74640cfe6'
proof=ROOT/'engine/rust/cp-proof-ffi'
if not (proof/'target').exists():
    (CACHE/'proof-target').mkdir(exist_ok=True)
    (proof/'target').symlink_to(CACHE/'proof-target',target_is_directory=True)
env=os.environ.copy()
env.update(PATH=str(CACHE/'rust/bin')+':'+str(cuda/'bin')+':'+env['PATH'],
           CARGO_HOME=str(CACHE/'cargo'),CARGO_BUILD_JOBS='2',
           CC=str(wrappers/'cc'),CXX=str(wrappers/'cxx'),
           CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=str(wrappers/'cc'),
           LD_LIBRARY_PATH=str(cuda/'lib'))
run(['cmake','-S',ROOT/'engine','-B',CACHE/'build','-DCMAKE_BUILD_TYPE=Release',
     '-DCMAKE_C_COMPILER='+env['CC'],'-DCMAKE_CXX_COMPILER='+env['CXX'],
     '-DCMAKE_CUDA_COMPILER='+str(cuda/'bin/nvcc'),'-DCMAKE_CUDA_HOST_COMPILER='+env['CXX'],
     '-DCUDAToolkit_ROOT='+str(cuda),'-DCP_ENABLE_CPU=OFF','-DCP_ENABLE_CUDA=ON',
     '-DCP_ENABLE_OPENCL=OFF','-DCP_ENABLE_CUBLAS=ON','-DCP_CUDA_ARCH=86',
     '-DCMAKE_CUDA_ARCHITECTURES=86','-DPRL_ALLOW_PROOF_STUB_TEST_ONLY=OFF',
     '-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON','-DCMAKE_INSTALL_RPATH=$ORIGIN/lib'],env=env)
run(['cmake','--build',CACHE/'build','-j','2'],env=env)
run(['cargo','test','--release','--locked','--manifest-path',proof/'Cargo.toml','-j','2'],env=dict(env,CARGO_TARGET_DIR=str(proof/'target')))
run(['python3',ROOT/'tests/test_runtime.py'])
with (CACHE/'cuda-targets.txt').open('w') as out:run([cuda/'bin/cuobjdump','--list-elf',CACHE/'build/cppminer'],stdout=out)
with (CACHE/'cargo-metadata.json').open('w') as out:
    run(['cargo','metadata','--locked','--format-version','1','--filter-platform','x86_64-unknown-linux-gnu','--manifest-path',proof/'Cargo.toml'],env=env,stdout=out)
print('BUILD AND LOCAL TESTS PASSED. GPU and real pool acceptance remain untested.',flush=True)
