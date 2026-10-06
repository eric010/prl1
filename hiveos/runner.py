#!/usr/bin/env python3
"""PRL3060 experimental HiveOS supervisor. Python >=3.8, standard library only."""
import argparse
import csv
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

VERSION = '0.1.0-experimental'
RATE = re.compile(r'([0-9.]+) ([KMGTP]?)MAC/s')
UNITS = {'': 1, 'K': 1e3, 'M': 1e6, 'G': 1e9, 'T': 1e12, 'P': 1e15}

def validate(config):
    c = dict(config)
    endpoint = c.get('pool', 'stratum+tcp://prl.kryptex.network:7048')
    endpoint = endpoint.removeprefix('stratum+tcp://') if hasattr(str, 'removeprefix') else endpoint.replace('stratum+tcp://', '', 1)
    if not re.fullmatch(r'[a-zA-Z0-9.-]+:[0-9]{1,5}', endpoint):
        raise ValueError('Só TCP nesta versão. Usa stratum+tcp://prl.kryptex.network:7048.')
    host, port = endpoint.rsplit(':', 1)
    if not 1 <= int(port) <= 65535 or int(port) == 8048:
        raise ValueError('Porta TCP inválida; a porta SSL 8048 não é suportada.')
    if not (host == 'prl.kryptex.network' or re.fullmatch(r'prl-[a-z]{2}\.kryptex\.network', host)):
        raise ValueError('Esta configuração destina-se apenas à pool Pearl da Kryptex.')
    c['pool'] = 'stratum+tcp://' + endpoint
    for k, limit in [('wallet', 240), ('worker', 45), ('password', 240)]:
        value = c.get(k, 'x' if k == 'password' else '')
        if not isinstance(value, str) or not value or len(value) > limit or any(ord(x) < 32 for x in value):
            raise ValueError('Campo inválido: ' + k)
        if '%' in value or 'YOUR_' in value or 'COLOCA_' in value:
            raise ValueError('Preenche o campo ' + k)
        c[k] = value
    if '/' in c['wallet']:
        raise ValueError('Separa o utilizador/carteira do nome do worker.')
    ids = c.get('devices', [0])
    if not isinstance(ids, list) or not ids or any(type(x) is not int or x < 0 or x > 31 for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('devices tem de ser uma lista de índices únicos, por exemplo [0,1,2,3].')
    c['devices'] = ids
    c['row_batch'] = c.get('row_batch', 4)
    c['col_batch'] = c.get('col_batch', 32)
    if any(type(c[k]) is not int or not 1 <= c[k] <= 128 for k in ['row_batch', 'col_batch']):
        raise ValueError('Tamanho de batch inválido.')
    if c['row_batch'] * c['col_batch'] > 256:
        raise ValueError('O histórico ultrapassaria 1 GiB; reduz o batch para este perfil de 8 GB.')
    return c

def read_gpus():
    result = subprocess.run(['nvidia-smi', '--query-gpu=index,name,pci.bus_id,compute_cap,memory.total,temperature.gpu,fan.speed,power.draw', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=15, check=True)
    out = {}
    for row in csv.reader(result.stdout.splitlines(), skipinitialspace=True):
        if len(row) != 8: continue
        def number(s):
            try: return float(s.strip())
            except ValueError: return None
        i, name, bus, cap, mem, temp, fan, power = [x.strip() for x in row]
        out[int(i)] = dict(name=name, bus=bus, cap=cap, memory=number(mem), temp=number(temp), fan=number(fan), power=number(power))
    return out

def command(binary, c, device):
    return [str(binary), '--backend', 'cuda', '--cublas-period', '--step-major',
            '--devices', str(device), '--pool', c['pool'], '--wallet', c['wallet'],
            '--worker', c['worker'] + '-gpu' + str(device), '--password', c['password'],
            '--row-period-batch', str(c['row_batch']), '--period-batch', str(c['col_batch']), '--verify']

class Metrics:
    def __init__(self, devices):
        self.lock = threading.Lock()
        self.rows = {i: dict(hs=0.0, rate_at=0.0, accepted=0, rejected=0, connected=False, running=False) for i in devices}
        self.start = time.time()
    def consume(self, device, line):
        with self.lock:
            row = self.rows[device]
            if line.startswith('[prl-event] '):
                try: e = json.loads(line[len('[prl-event] '):])
                except ValueError: return
                kind = e.get('type')
                if kind == 'authorized': row['connected'] = e.get('ok') is True
                elif kind == 'disconnected': row.update(connected=False, hs=0.0, rate_at=0.0)
                elif kind == 'share':
                    row['accepted' if e.get('accepted') is True else 'rejected'] += 1
            # Ignore prep/kernel-only benchmarks: report the engine's complete
            # search interval, not the inner kernel's peak throughput.
            elif line.startswith('[plain] ') and ('no share yet' in line or 'proof ready' in line):
                m = RATE.search(line)
                if m:
                    v = float(m.group(1)) * UNITS[m.group(2)]
                    if math.isfinite(v) and v >= 0: row.update(hs=v, rate_at=time.time())
    def snapshot(self, gpus):
        with self.lock:
            now = time.time()
            rows = []
            for i, raw in self.rows.items():
                r = dict(raw); r['id'] = i
                if not r['running'] or not r['connected'] or now - r['rate_at'] > 120: r['hs'] = 0.0
                r.update(gpus.get(i, {})); rows.append(r)
            hive = dict(hs=[r['hs'] for r in rows], hs_units='hs',
                        temp=[r.get('temp') for r in rows], fan=[r.get('fan') for r in rows],
                        bus_numbers=[int(r['bus'].split(':')[-2], 16) if r.get('bus') else None for r in rows],
                        ar=[sum(r['accepted'] for r in rows), sum(r['rejected'] for r in rows)],
                        uptime=int(now-self.start), algo='pearlhash', ver=VERSION)
            return dict(updated=now, gpus=rows, total_khs=sum(r['hs'] for r in rows)/1000, hive=hive)

def atomic_json(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, allow_nan=False))
    os.replace(str(temp), str(path))

def run(config, directory):
    c = validate(config)
    binary = directory / 'prl3060-engine'
    if not binary.is_file() or not os.access(str(binary), os.X_OK):
        raise ValueError('Falta o executável CUDA compilado. Este pacote de fontes não está pronto para minerar.')
    gpus = read_gpus()
    for i in c['devices']:
        if i not in gpus or gpus[i]['cap'] != '8.6' or (gpus[i]['memory'] or 0) < 7900:
            raise ValueError('GPU %s não corresponde ao perfil Ampere sm_86 com pelo menos 8 GB.' % i)
    stop = threading.Event(); failed = threading.Event(); children = []; threads = []
    metrics = Metrics(c['devices'])
    for sig in [signal.SIGINT, signal.SIGTERM]: signal.signal(sig, lambda *_: stop.set())
    state = directory / 'stats.json'
    env = os.environ.copy()
    env['OMP_NUM_THREADS'] = '1'; env['RAYON_NUM_THREADS'] = '1'
    env['LD_LIBRARY_PATH'] = str(directory / 'lib') + ':' + env.get('LD_LIBRARY_PATH', '')
    def read_output(device, proc):
        try:
            for line in proc.stdout:
                metrics.consume(device, line.rstrip())
                print('[GPU%d] %s' % (device, line.rstrip()), flush=True)
        finally:
            proc.stdout.close()
            with metrics.lock: metrics.rows[device].update(running=False, connected=False, hs=0.0)
            if not stop.is_set():
                failed.set()
                print('GPU%d terminou. A sessão experimental vai parar; consulta o erro acima.' % device, flush=True)
                stop.set()
    try:
        for i in c['devices']:
            workdir = directory / 'run' / ('gpu%d' % i)
            workdir.mkdir(parents=True, exist_ok=True, mode=0o700)
            device_env = dict(env, PRL_WORKDIR=str(workdir.resolve()))
            p = subprocess.Popen(command(binary, c, i), cwd=str(workdir), env=device_env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 bufsize=1, start_new_session=True)
            children.append(p)
            metrics.rows[i]['running'] = True
            t = threading.Thread(target=read_output, args=(i,p), daemon=True); t.start(); threads.append(t)
        next_sensors = 0
        while not stop.wait(2):
            if time.monotonic() >= next_sensors:
                try: gpus = read_gpus()
                except (OSError, subprocess.SubprocessError):
                    gpus = {}  # do not report stale temperatures as live
                next_sensors = time.monotonic()+10
            atomic_json(state, metrics.snapshot(gpus))
    finally:
        for p in children:
            if p.poll() is None:
                try: os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError: pass
        deadline = time.monotonic()+8
        for p in children:
            try: p.wait(timeout=max(0.1, deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                try: os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                p.wait()
        for t in threads: t.join(timeout=2)
        with metrics.lock:
            for row in metrics.rows.values(): row.update(running=False, connected=False, hs=0.0)
        atomic_json(state, metrics.snapshot(gpus))
    return 1 if failed.is_set() else 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).resolve().parent / 'config.json'))
    parser.add_argument('--check-config', action='store_true')
    args = parser.parse_args()
    try:
        c = validate(json.loads(Path(args.config).read_text()))
        if args.check_config:
            print('Configuração válida; isto não verifica a GPU, a pool ou shares.'); return 0
        return run(c, Path(__file__).resolve().parent)
    except (ValueError, OSError, subprocess.SubprocessError) as e:
        print('ERRO: ' + str(e), file=sys.stderr); return 1
if __name__ == '__main__': sys.exit(main())
