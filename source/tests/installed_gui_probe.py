#!/usr/bin/python3
"""Read native Core/desktop state only inside the owned offline QEMU fixture."""
import argparse,hashlib,json,os,pwd,re,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('phase',choices=['gui-desktop','gui-reboot-desktop','gui-running','gui-reopened','gui-stopped']);p.add_argument('--media',type=Path,required=True);a=p.parse_args()
assert os.environ.get('NODE_VM_ACCEPTANCE')=='1' and os.getuid()==pwd.getpwnam('node').pw_uid
assert 'Q35' in Path('/sys/devices/virtual/dmi/id/product_name').read_text()
assert sorted(x.name for x in Path('/sys/class/net').iterdir())==['lo']
assert 'boot=live' not in Path('/proc/cmdline').read_text().split()
assert subprocess.check_output(['findmnt','-n','-o','SOURCE','/'],text=True).strip() in ['/dev/vda1','/dev/vda2']
assert (a.media/'NODE-TEST-ONLY').read_text().strip()=='disposable QEMU fixture'
sys.path.insert(0,'/usr/lib/bitcoin-core-node')
from state import CORE_GUI_SHA256
from rpc import CoreRPC
report={'phase':a.phase,'covered':[],'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
try:
 xset=subprocess.check_output(['xset','q'],text=True)
 assert re.search(r'Num Lock:\s+on',xset),xset
 assert Path('/usr/local/bin/core-node-taskbar').is_file()
 assert subprocess.run(['pgrep','-f','^/usr/bin/python3 /usr/local/bin/core-node-taskbar$'],capture_output=True).returncode == 0
 report['covered'].append('Num Lock is on in the actual X session; Vault-derived taskbar is running')
 active=subprocess.run(['systemctl','is-active','--quiet','bitcoin-core-node.service']).returncode==0
 if a.phase in ['gui-desktop','gui-reboot-desktop','gui-stopped']:
  assert not active
  assert not Path('/run/bitcoin-core-node/auth.cookie').exists()
  report['covered'].append('Core is stopped until explicitly opened; no background RPC daemon')
 else:
  assert active
  pid=int(subprocess.check_output(['systemctl','show','--property=MainPID','--value','bitcoin-core-node.service'],text=True))
  assert (Path('/proc')/str(pid)/'comm').read_text().strip()=='bitcoin-qt'
  assert (Path('/proc')/str(pid)).stat().st_uid==pwd.getpwnam('bitcoinnode').pw_uid
  binary=Path('/opt/bitcoin-core/32.1/bin/bitcoin-qt')
  assert hashlib.sha256(binary.read_bytes()).hexdigest()==CORE_GUI_SHA256
  rpc=CoreRPC();chain=rpc('getblockchaininfo')
  assert chain['pruned'] is True
  report.update(core_pid=pid,network=chain['chain'],blocks=chain['blocks'],bestblockhash=chain['bestblockhash'],pruned=chain['pruned'],prune_target_size=chain.get('prune_target_size'))
  report['covered'].append('Verified upstream bitcoin-qt runs as the unprivileged Core account; native prune preference is active over shared local RPC')
  if a.phase=='gui-reopened':
   assert chain['chain']=='regtest' and chain['blocks']==101
   assert 'onboarding' in rpc('listwallets')
   assert rpc('getwalletinfo',wallet='onboarding')['private_keys_enabled'] is False
   report['covered'].append('Reopening the native GUI retains the funded public wallet and 101-block chain')
 report['status']='passed-covered-checks'
except Exception as e:report.update(status='failed',error=repr(e));raise
finally:
 (a.media/('onboarding-'+a.phase+'-result.json')).write_text(json.dumps(report,indent=2)+'\n');os.sync()
