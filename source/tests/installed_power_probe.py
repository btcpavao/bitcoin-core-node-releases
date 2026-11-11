#!/usr/bin/python3
"""Exercise native GUI persistence only in an owned installed regtest VM."""
import argparse,json,os,pwd,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('phase',choices=['power-seed','power-verify'])
p.add_argument('--media',type=Path,required=True)
a=p.parse_args()
assert os.environ.get('NODE_VM_ACCEPTANCE')=='1'
assert os.getuid()==pwd.getpwnam('node').pw_uid
assert 'Q35' in Path('/sys/devices/virtual/dmi/id/product_name').read_text()
assert sorted(x.name for x in Path('/sys/class/net').iterdir())==['lo']
assert 'boot=live' not in Path('/proc/cmdline').read_text().split()
assert subprocess.check_output(['findmnt','-n','-o','SOURCE','/'],text=True).strip() in ['/dev/vda1','/dev/vda2']
assert (a.media/'NODE-TEST-ONLY').read_text().strip()=='disposable QEMU fixture'
sys.path.insert(0,'/usr/lib/bitcoin-core-node')
from rpc import CoreRPC
rpc=CoreRPC()
state=Path.home()/'.local/state/node-power-acceptance.json'
report={'phase':a.phase,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'covered':[]}
try:
    assert rpc('getblockchaininfo')['chain']=='regtest'
    assert rpc('getwalletinfo',wallet='onboarding')['private_keys_enabled'] is False
    after=subprocess.check_output(['systemctl','show','bitcoin-core-node.service','--property=After','--value'],text=True).split()
    binds=subprocess.check_output(['systemctl','show','bitcoin-core-node.service','--property=BindsTo','--value'],text=True).split()
    session='session-'+os.environ['XDG_SESSION_ID']+'.scope'
    assert session in after and session in binds,(after,binds)
    report['covered'].append('Core stops before the active desktop session and is bound to its lifetime')
    if a.phase=='power-seed':
        address=rpc('getnewaddress','Power persistence','bech32',wallet='onboarding')
        rpc('generatetoaddress',101,address)
        rpc('syncwithvalidationinterfacequeue')
        report['address']=address
    else:
        previous=json.loads(state.read_text())
        assert previous['boot_id']!=report['boot_id']
        assert rpc('getbestblockhash')==previous['tip']
        assert rpc('getblockcount')==previous['blocks']
        assert rpc('getaddressinfo',previous['address'],wallet='onboarding')['labels']==['Power persistence']
        report['covered'].append('Actual GUI restart retains the exact chain tip, height, public wallet and address label')
    report.update(tip=rpc('getbestblockhash'),blocks=rpc('getblockcount'),status='passed-covered-checks')
    if a.phase=='power-seed':state.write_text(json.dumps(report,indent=2))
except Exception as e:
    report.update(status='failed',error=repr(e))
    raise
finally:
    (a.media/('onboarding-'+a.phase+'-result.json')).write_text(json.dumps(report,indent=2)+'\n')
    os.sync()
