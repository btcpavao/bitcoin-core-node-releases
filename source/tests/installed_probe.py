#!/usr/bin/python3
"""Explicit disposable QEMU guest acceptance. Never run on a normal host."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import time

parser=argparse.ArgumentParser()
parser.add_argument('phase',choices=['configure','reboot'])
parser.add_argument('--media',type=Path,required=True)
args=parser.parse_args()
assert os.geteuid()==0 and os.environ.get('NODE_VM_ACCEPTANCE')=='1'
assert 'Q35' in Path('/sys/devices/virtual/dmi/id/product_name').read_text()
assert sorted(p.name for p in Path('/sys/class/net').iterdir())==['lo']
assert 'boot=live' not in Path('/proc/cmdline').read_text().split()
source=subprocess.check_output(['findmnt','-n','-o','SOURCE','/'],text=True).strip()
assert source in ('/dev/vda1','/dev/vda2'),source
assert Path('/etc/bitcoin-core-node/installed').is_file()
assert args.media.is_dir() and (args.media/'NODE-TEST-ONLY').read_text().strip()=='disposable QEMU fixture'
assert os.statvfs('/').f_blocks*os.statvfs('/').f_frsize<52*1024**3
sys.path.insert(0,'/usr/lib/bitcoin-core-node')
from rpc import CoreRPC
from wallets import WalletService
from state import CORE_SHA256

def run(command,**kwargs):
    return subprocess.run(command,check=True,capture_output=True,text=True,timeout=120,**kwargs)

def wait_core():
    rpc=CoreRPC()
    for _ in range(300):
        try:
            assert rpc('getblockchaininfo')['chain']=='regtest'
            return rpc
        except Exception:time.sleep(.1)
    raise RuntimeError('Installed Core did not start.')

report={'phase':args.phase,'covered':[],'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
def passed(check):report['covered'].append(check);print('PASS '+check,flush=True)
try:
    accounts=Path('/etc/passwd').read_text().splitlines()
    assert not any(row.startswith('node-live:') for row in accounts)
    assert pwd.getpwnam('nodecheck').pw_uid>=1000
    assert all('NOPASSWD' not in p.read_text() for p in Path('/etc/sudoers.d').iterdir() if p.is_file())
    shadow={row.split(':')[0]:row.split(':')[1] for row in Path('/etc/shadow').read_text().splitlines()}
    assert shadow['nodecheck'].startswith('$') and shadow['root'].startswith(('!','*'))
    assert run(['runuser','-u','nodecheck','--','sudo','-k','-n','true']).returncode!=0
except subprocess.CalledProcessError as exc:
    if exc.cmd[-4:]!=['sudo','-k','-n','true']:raise
    passed('installed named account, locked root and authentication required')
else:
    raise AssertionError('Installed account unexpectedly ran sudo without authentication.')

try:
    binary=Path('/opt/bitcoin-core/32.1/bin/bitcoind')
    assert hashlib.sha256(binary.read_bytes()).hexdigest()==CORE_SHA256
    passed('installed daemon matches verified upstream executable')
    if args.phase=='configure':
        assert not Path('/etc/bitcoin-core-node/setup.json').exists()
        assert subprocess.run(['systemctl','is-active','--quiet','bitcoin-core-node']).returncode!=0
        passed('first boot does not start unconfirmed Core')
        setup={'version':1,'confirmed':True,'profile':'clearnet','network':'regtest','prune_mib':0,'data_uuid':None,'private_broadcast':False}
        run(['/usr/libexec/core-node-admin','configure'],input=json.dumps({'setup':setup}))
        rpc=wait_core();service=WalletService(rpc,Path('/root/node-acceptance-records'))
        rpc('restorewallet','vmwatch',str(args.media/'watch-only.dat'),True)
        address=service.receive('vmwatch','Installed reboot fixture','bech32')
        blocks=rpc('generatetoaddress',101,address)
        rpc('syncwithvalidationinterfacequeue')
        assert service.snapshot('vmwatch')['utxos']
        report.update(address=address,tip=blocks[-1],height=101)
        passed('installed service imports public descriptors and retains funded watch-only wallet')
        snapshot=json.loads(run(['/usr/libexec/core-node-admin','wallet-snapshot'],input=json.dumps({'wallet':'vmwatch'})).stdout)
        database=base64.b64decode(snapshot['data'],validate=True)
        assert hashlib.sha256(database).hexdigest()==snapshot['sha256']
        assert database.startswith(b'SQLite format 3\0')
        passed('installed narrow native snapshot helper returns verified watch-only database')
        run(['pkill','-u','nodecheck','-f','/usr/local/bin/bitcoin-core-node'])
        time.sleep(1)
        assert run(['systemctl','is-active','bitcoin-core-node']).stdout.strip()=='active'
        assert rpc('getblockcount')==101
        passed('closing Home leaves installed system service running')
        Path('/var/lib/bitcoin-core-node/acceptance.json').write_text(json.dumps(report))
    else:
        previous=json.loads(Path('/var/lib/bitcoin-core-node/acceptance.json').read_text())
        assert previous['boot_id']!=report['boot_id']
        rpc=wait_core();service=WalletService(rpc,Path('/root/node-acceptance-records'))
        assert 'vmwatch' in rpc('listwallets')
        assert rpc('getblockcount')==previous['height'] and rpc('getbestblockhash')==previous['tip']
        assert service.watch('vmwatch')['private_keys_enabled'] is False
        assert rpc('getaddressinfo',previous['address'],wallet='vmwatch')['labels']==['Installed reboot fixture']
        assert service.snapshot('vmwatch')['utxos']
        passed('real installed reboot preserves settings, loaded wallet, labels, UTXOs and validated block tip')
    report['status']='passed-covered-checks'
except Exception as exc:
    report.update(status='failed',error=repr(exc));raise
finally:
    (args.media/('installed-'+args.phase+'-result.json')).write_text(json.dumps(report,indent=2))
    os.sync()
