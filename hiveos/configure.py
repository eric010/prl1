#!/usr/bin/env python3
import json, os, shlex
from pathlib import Path
from runner import validate, atomic_json

def from_hive(env):
    login = env.get('CUSTOM_TEMPLATE', '').strip()
    if '/' in login: wallet, worker = login.rsplit('/', 1)
    else: wallet, worker = login, env.get('WORKER_NAME', '3060tix4')
    pools = env.get('CUSTOM_URL', 'stratum+tcp://prl.kryptex.network:7048').split()
    if len(pools) != 1: raise ValueError('Usa apenas um endereço de pool nesta versão.')
    c = dict(wallet=wallet, worker=worker, pool=pools[0], password=env.get('CUSTOM_PASS', '') or 'x', devices=[0])
    flags = shlex.split(env.get('CUSTOM_USER_CONFIG', ''))
    i = 0
    while i < len(flags):
        key = flags[i]
        if key not in ['--devices','--row-batch','--col-batch'] or i+1 >= len(flags):
            raise ValueError('Opção não suportada: ' + key)
        value = flags[i+1]; i += 2
        if key == '--devices': c['devices'] = [int(x) for x in value.split(',')]
        else: c[key[2:].replace('-', '_')] = int(value)
    return validate(c)
if __name__ == '__main__':
    try:
        path = Path(os.environ.get('CUSTOM_CONFIG_FILENAME', str(Path(__file__).resolve().parent / 'config.json')))
        atomic_json(path, from_hive(os.environ))
        path.chmod(0o600)
    except (ValueError, OSError) as e: raise SystemExit('Configuração inválida: ' + str(e))
