import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hiveos'))
from runner import validate, Metrics, command, run
from configure import from_hive

BASE = dict(wallet='krxTESTACCOUNT',worker='3060tix4',password='x',pool='stratum+tcp://prl.kryptex.network:7048')
class RuntimeTests(unittest.TestCase):
    def test_hive_sources_config_with_unexported_variables(self):
        script=Path(__file__).resolve().parents[1]/'hiveos'/'h-config.sh'
        with tempfile.TemporaryDirectory() as d:
            config=Path(d)/'config.json'
            code='''miner_config_gen() { printf parent; }
miner_config_echo() { printf echo-parent; }
CUSTOM_TEMPLATE=krxTESTACCOUNT/3060tix4
CUSTOM_URL=stratum+tcp://prl-eu.kryptex.network:7048
CUSTOM_USER_CONFIG="--devices 0"
CUSTOM_CONFIG_FILENAME=$2
config_gen() { source "$1"; }
config_gen "$1" || exit $?
test "$(miner_config_gen)" = parent && test "$(miner_config_echo)" = echo-parent
'''
            subprocess.run(['bash','-c',code,'test',str(script),str(config)],check=True)
            c=json.loads(config.read_text())
            self.assertEqual(c['wallet'],'krxTESTACCOUNT')
            self.assertEqual(c['worker'],'3060tix4')
            self.assertEqual(c['devices'],[0])
            self.assertEqual(config.stat().st_mode & 0o777,0o600)
    def test_hive_config_missing_wallet_fails(self):
        script=Path(__file__).resolve().parents[1]/'hiveos'/'h-config.sh'
        with tempfile.TemporaryDirectory() as d:
            config=Path(d)/'config.json'
            code='CUSTOM_TEMPLATE=""; CUSTOM_CONFIG_FILENAME=$2; source "$1"'
            result=subprocess.run(['bash','-c',code,'test',str(script),str(config)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(config.exists())
    def test_separate_gpu_workdirs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);engine=root/'prl3060-engine'
            engine.write_text('#!/usr/bin/env python3\nimport os,time\nfrom pathlib import Path\np=Path(os.environ["PRL_WORKDIR"])\n(p/"proof-test").write_text(str(p))\ntime.sleep(0.2)\n')
            engine.chmod(0o755)
            with patch('runner.read_gpus',return_value={i:dict(cap='8.6',memory=8192) for i in [0,1]}):
                self.assertEqual(run(dict(BASE,devices=[0,1]),root),1)
            for i in [0,1]:
                p=root/'run'/('gpu%d'%i)
                self.assertEqual((p/'proof-test').read_text(),str(p))
    def test_account_template(self):
        c=from_hive(dict(CUSTOM_TEMPLATE='krxTESTACCOUNT/3060tix4',CUSTOM_URL=BASE['pool'],CUSTOM_USER_CONFIG='--devices 0,1,2,3'))
        self.assertEqual(c['wallet'],BASE['wallet']);self.assertEqual(c['devices'],[0,1,2,3])
    def test_invalid_configs(self):
        for extra in [dict(pool='stratum+ssl://prl.kryptex.network:8048'),dict(pool='evil.example:7048'),dict(pool='prl.kryptex.network:8048'),dict(devices=[0,0]),dict(row_batch=32,col_batch=1024),dict(wallet='COLOCA_AQUI'),dict(devices=[True])]:
            with self.subTest(extra=extra),self.assertRaises(ValueError): validate(dict(BASE,**extra))
    def test_no_shell_config_execution(self):
        with tempfile.TemporaryDirectory() as d:
            marker=Path(d)/'should-not-exist'
            c=dict(BASE,worker='$(touch '+str(marker)+')')
            # Long path may be refused; otherwise remains one subprocess argv.
            c['worker']='$(touch /tmp/never-run-prl)'
            args=command(Path('/bin/echo'),validate(c),0)
            self.assertIn(c['worker']+'-gpu0',args)
            with self.assertRaises(ValueError): from_hive(dict(CUSTOM_TEMPLATE='test/w',CUSTOM_USER_CONFIG='; touch '+str(marker)))
            self.assertFalse(marker.exists())
    def test_only_pool_ack_counts(self):
        m=Metrics([0]);m.rows[0]['running']=True
        m.consume(0,'[prl-event] {"type":"authorized","ok":true}')
        m.consume(0,'[prl-event] {"type":"submitted","id":2}')
        self.assertEqual(m.snapshot({})['hive']['ar'],[0,0])
        m.consume(0,'[prl-event] {"type":"share","accepted":true,"id":2}')
        m.consume(0,'[prl-event] {"type":"share","accepted":false,"id":3}')
        self.assertEqual(m.snapshot({})['hive']['ar'],[1,1])
    def test_rate_units_and_disconnect(self):
        m=Metrics([0]);m.rows[0].update(running=True,connected=True)
        m.consume(0,'[gpu] attempt timing: prep=0.1s scan=1s 500 TMAC/s')
        self.assertEqual(m.snapshot({})['total_khs'],0)
        m.consume(0,'[plain] nonce=1 attempts=1 (1.00/s) 55.00 TMAC/s no share yet')
        self.assertEqual(m.snapshot({})['total_khs'],55e9)
        m.rows[0]['rate_at']=time.time()-121
        self.assertEqual(m.snapshot({})['total_khs'],0)
        m.consume(0,'[prl-event] {"type":"disconnected"}')
        self.assertFalse(m.snapshot({})['gpus'][0]['connected'])
    def test_shell_stats_units_and_stale_state(self):
        root=Path(__file__).resolve().parents[1]/'hiveos'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'h-stats.sh').write_text((root/'h-stats.sh').read_text())
            state=dict(updated=time.time(),hive=dict(hs=[52e12,49e12],hs_units='hs'))
            (p/'stats.json').write_text(json.dumps(state))
            code='source "$1"; python3 - "$khs" "$stats" <<\'END\'\nimport json,sys\nprint(json.dumps([float(sys.argv[1]),json.loads(sys.argv[2])]))\nEND'
            data=json.loads(subprocess.check_output(['bash','-c',code,'test',str(p/'h-stats.sh')],text=True))
            self.assertEqual(data[0],101e9)
            state['updated']=time.time()-40;(p/'stats.json').write_text(json.dumps(state))
            data=json.loads(subprocess.check_output(['bash','-c',code,'test',str(p/'h-stats.sh')],text=True))
            self.assertEqual(data,[0,None])
if __name__=='__main__':unittest.main()
