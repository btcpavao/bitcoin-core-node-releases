#!/usr/bin/python3
"""Re-run USB exchange using the exact rebuilt UEFI Node image and clean Vault RAM."""
from pathlib import Path
import json,os,subprocess,time
base=Path.home()/'node-v1-validation';repo=Path(__file__).resolve().parents[1]
node=base/'uefi-82c2301';vault=base/'vault-exchange-9e94867';media=base/'exchange-82c2301.img'
env=os.environ.copy();env['PATH']=str(base/'bin')+':'+env['PATH']
def call(root,action,*opts):return subprocess.run(['python3',str(repo/'tests/vm_probe.py'),action,'--root',str(root),*opts],env=env,capture_output=True,text=True,check=True,timeout=120).stdout.strip()
def type_text(root,text):call(root,'type','--text',text)
def wait(root,label,predicate,tty=False):
 for i in range(120):
  path=call(root,'screen');text=subprocess.run(['tesseract',path,'stdout','--psm','6'],env=env,capture_output=True,text=True,check=True).stdout.lower()
  if predicate(text):print('Observed '+label,flush=True);return
  if tty and i%5==0:call(root,'key','--keys','ret' if 'gnu grub' in text else 'ctrl-alt-f2')
  if i%15==0:print('Waiting '+label,flush=True)
  time.sleep(2)
 raise RuntimeError('Deadline '+label+': '+text)
for root in [node,vault]:
 record=json.loads((root/'fixture.json').read_text());proc=Path('/proc')/str(record['pid'])/'cmdline'
 assert not proc.exists() or not proc.read_bytes()
 assert not record.get('usb') and record['command'][record['command'].index('-nic')+1]=='none'
 p=subprocess.Popen(record['command'],stdout=open(root/'qemu-exact-exchange.log','ab'),stderr=subprocess.STDOUT,start_new_session=True);record['pid']=p.pid;(root/'fixture.json').write_text(json.dumps(record,indent=2)+'\n')
wait(node,'installed login',lambda s:'login:' in s,True);type_text(node,'nodecheck\n')
wait(node,'password',lambda s:'password:' in s);type_text(node,'NodeFixture-2026!\n')
wait(node,'account',lambda s:'nodecheck@node-fixture' in s);type_text(node,'sudo -i\n')
wait(node,'administrative authentication',lambda s:'password for nodecheck' in s);type_text(node,'NodeFixture-2026!\n')
wait(node,'root console',lambda s:'root@node-fixture' in s)
wait(vault,'Vault boot menu',lambda s:'start bitcoin core vault' in s);call(vault,'key','--keys','ret')
wait(vault,'Vault private session',lambda s:'wallet backup' in s and 'terminal' in s)
call(vault,'click','--label','Terminal');wait(vault,'Vault terminal',lambda s:'vault@core-vault' in s)
with media.open('xb') as f:f.truncate(32*1024*1024)
subprocess.run(['/usr/sbin/mkfs.fat','-n','NODE_TEST',str(media)],check=True)
for path in [base/'NODE-TEST-ONLY',repo/'tests/installed_exchange_probe.py']:
 subprocess.run(['mcopy','-i',str(media),str(path),'::'+path.name],check=True,timeout=30)
r=subprocess.run(['python3',str(repo/'tests/exchange_vm.py'),'--node',str(node),'--vault',str(vault),'--usb',str(media)],env=env)
assert r.returncode==0
call(vault,'stop');type_text(node,'systemctl poweroff\n')
print('PASS exact rebuilt Node / Vault OS exchange and cleanup',flush=True)
