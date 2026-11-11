#!/usr/bin/python3
"""Exercise actual local-session authorization on disposable installed QEMU only."""
import argparse,base64,hashlib,json,os,pwd,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('phase',choices=['before','password','reboot','autologin','default-reboot']);p.add_argument('--media',type=Path,required=True);a=p.parse_args()
assert os.environ.get('NODE_VM_ACCEPTANCE')=='1' and os.getuid()==pwd.getpwnam('node').pw_uid
assert 'Q35' in Path('/sys/devices/virtual/dmi/id/product_name').read_text()
assert sorted(x.name for x in Path('/sys/class/net').iterdir())==['lo']
assert 'boot=live' not in Path('/proc/cmdline').read_text().split()
assert subprocess.check_output(['findmnt','-n','-o','SOURCE','/'],text=True).strip() in ['/dev/vda1','/dev/vda2']
assert os.statvfs('/').f_blocks*os.statvfs('/').f_frsize<52*1024**3
assert (a.media/'NODE-TEST-ONLY').read_text().strip()=='disposable QEMU fixture'
sys.path.insert(0,'/usr/lib/bitcoin-core-node')
from state import load_setup,default_setup,CORE_SHA256
from rpc import CoreRPC
from wallets import WalletService
from login import passwordless
state=Path.home()/'.local/state/node-onboarding-acceptance';state.mkdir(parents=True,exist_ok=True)
rpc=CoreRPC();report={'phase':a.phase,'covered':[],'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
def passed(s):report['covered'].append(s);print('PASS '+s,flush=True)
def run(args,**kw):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=180,**kw)
def helper(path,action,request=None):
 return json.loads(run(['pkexec','/usr/libexec/'+path,action],input='' if request is None else json.dumps(request)).stdout)
def permission(action):
 return subprocess.run(['pkcheck','--action-id',action,'--process',str(os.getpid())],capture_output=True).returncode
def ready(chain):
 for _ in range(300):
  try:
   assert rpc('getblockchaininfo')['chain']==chain;return
  except Exception:time.sleep(.1)
 raise RuntimeError('Installed Core is unavailable')
def retained():
 previous=json.loads((state/'before.json').read_text());ready('regtest')
 assert rpc('getbestblockhash')==previous['tip'] and rpc('getblockcount')==101
 assert 'onboarding' in rpc('listwallets')
 assert rpc('getwalletinfo',wallet='onboarding')['private_keys_enabled'] is False
 assert rpc('getaddressinfo',previous['address'],wallet='onboarding')['labels']==['Onboarding persistence']
 return previous
try:
 assert Path('/etc/bitcoin-core-node/installed').is_file()
 assert not any(x.startswith('node-live:') for x in Path('/etc/passwd').read_text().splitlines())
 assert hashlib.sha256(Path('/opt/bitcoin-core/32.1/bin/bitcoind').read_bytes()).hexdigest()==CORE_SHA256
 if a.phase=='before':
  assert load_setup()==default_setup();ready('main')
  assert passwordless()
  assert all(permission(x)==0 for x in ['org.bitcoin-core-node.admin','org.bitcoin-core-node.login'])
  assert subprocess.run(['sudo','-k','-n','true'],capture_output=True).returncode!=0
  assert os.environ.get('DISPLAY') and os.environ.get('XDG_SESSION_ID')
  passed('automatic local desktop login and running mainnet Core without a setup prompt; no generic passwordless sudo')
  helper('core-node-admin','configure',{'setup':{**default_setup(),'network':'regtest'}});ready('regtest')
  service=WalletService(rpc,state/'records');rpc('restorewallet','onboarding',str(a.media/'watch-only.dat'),True)
  address=service.receive('onboarding','Onboarding persistence','bech32')
  tip=rpc('generatetoaddress',101,address)[-1];rpc('syncwithvalidationinterfacequeue')
  assert service.snapshot('onboarding')['utxos']
  backup=helper('core-node-admin','wallet-snapshot',{'wallet':'onboarding'})
  data=base64.b64decode(backup['data']);assert data.startswith(b'SQLite format 3\0')
  assert hashlib.sha256(data).hexdigest()==backup['sha256']
  report.update(tip=tip,address=address)
  passed('bounded production administration works in the active automatic-login session, including public-wallet snapshot')
 elif a.phase=='password':
  assert not passwordless();retained()
  assert all(permission(x)!=0 for x in ['org.bitcoin-core-node.admin','org.bitcoin-core-node.login'])
  passed('enabling password removes password-free authorization for both administration and login changes')
  helper('core-node-admin','restart');ready('regtest');retained()
  passed('native polkit authentication permits an explicit service restart after password enablement')
 elif a.phase=='reboot':
  previous=retained();assert previous['boot_id']!=report['boot_id'];assert not passwordless()
  passed('actual reboot requires graphical password login and preserves wallet, labels and chain tip')
  helper('core-node-login','configure',{'required':False})
  assert passwordless();assert permission('org.bitcoin-core-node.admin')==0
  passed('return to automatic login requires native authentication with the existing password')
 elif a.phase=='default-reboot':
  previous=retained();assert previous['boot_id']!=report['boot_id'];assert passwordless()
  assert permission('org.bitcoin-core-node.admin')==0
  passed('actual reboot retains default automatic login, running Core and funded public-wallet state')
 else:
  retained();previous=json.loads((state/'reboot.json').read_text())
  assert previous['boot_id']!=report['boot_id'];assert passwordless()
  assert permission('org.bitcoin-core-node.admin')==0
  passed('second actual reboot restores automatic desktop login and retains Core service and public-wallet data')
 report['status']='passed-covered-checks'
except Exception as exc:report.update(status='failed',error=repr(exc));raise
finally:
 text=json.dumps(report,indent=2)+'\n';(state/(a.phase+'.json')).write_text(text)
 (a.media/('onboarding-'+a.phase+'-result.json')).write_text(text);os.sync()
