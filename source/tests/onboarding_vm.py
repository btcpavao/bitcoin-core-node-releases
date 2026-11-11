#!/usr/bin/python3
"""Observe native default-login acceptance on an owned, networkless QEMU fixture."""
import argparse,json,os,re,secrets,subprocess,time
from pathlib import Path
from PIL import Image
p=argparse.ArgumentParser();p.add_argument('action',choices=['boot','terminal','phase','set-password','home','reboot','login-screen','poweroff']);p.add_argument('--root',type=Path,required=True);p.add_argument('--usb',type=Path);p.add_argument('--phase',choices=['before','password','reboot','autologin','default-reboot','gui-desktop','gui-reboot-desktop','gui-running','gui-reopened','gui-stopped','power-seed','power-verify']);a=p.parse_args()
root=a.root.absolute();repo=Path(__file__).resolve().parents[1]
assert root.is_relative_to(Path.home()/'node-v1-validation') and not root.is_symlink()
record=json.loads((root/'fixture.json').read_text());assert record['command'][record['command'].index('-nic')+1]=='none'
assert str(root/'disk.qcow2') in ' '.join(record['command'])
report={'action':a.action,'phase':a.phase,'source_iso':record['iso'],'screens':[]}
def call(action,*opts):return subprocess.run(['python3',str(repo/'tests/vm_probe.py'),action,'--root',str(root),*opts],capture_output=True,text=True,check=True,timeout=120).stdout.strip()
def type_text(text):call('type','--text',text)
def screen():
 image=Path(call('screen'));text=subprocess.run(['tesseract',str(image),'stdout','--psm','6'],capture_output=True,text=True,check=True).stdout
 with Image.open(image) as frame:
  center=root/'onboarding-center.png';crop=frame.crop((frame.width//4,frame.height//4,frame.width*3//4,frame.height*3//4));crop.resize((crop.width*3,crop.height*3)).save(center)
 text+='\n'+subprocess.run(['tesseract',str(center),'stdout','--psm','6'],capture_output=True,text=True,check=True).stdout
 return image,text.lower().replace('?','')
def wait(label,predicate,timeout=300,authenticate=False):
 end=time.monotonic()+timeout;heartbeat=0;entered=False
 while time.monotonic()<end:
  try:image,text=screen()
  except subprocess.CalledProcessError:
   if time.monotonic()<end-timeout+20:time.sleep(1);continue
   raise
  if predicate(text):
   report['screens'].append({'label':label,'image':str(image),'text':text});print('Observed '+label+': '+str(image),flush=True);return text
  if authenticate and not entered and 'authenticate' in text and 'password' in text:
   report['screens'].append({'label':'native-authentication','image':str(image),'text':text})
   type_text('NodeFixture-2026!\n');entered=True
  if time.monotonic()>heartbeat:print('Waiting '+label,flush=True);heartbeat=time.monotonic()+30
  time.sleep(3)
 raise RuntimeError('Deadline '+label+': '+text)
try:
 if a.action=='boot':
  assert json.loads((root/'installer-result.json').read_text())['status']=='installed-awaiting-normal-reboot'
  call('installed');wait('automatic-installed-home',lambda s:'bitcoin core' in s and 'node guide' in s and 'install system to disk' not in s)
 elif a.action=='reboot':
  wait('active-desktop-terminal',lambda s:'node@bitcoin-core-node' in s)
  type_text('systemctl reboot\n');time.sleep(5)
 elif a.action=='login-screen':wait('password-login-screen',lambda s:'log in' in s)
 elif a.action=='poweroff':
  wait('active-desktop-terminal',lambda s:'node@bitcoin-core-node' in s);type_text('systemctl poweroff\n')
 elif a.action=='home':wait('installed-home',lambda s:'bitcoin core' in s and 'node guide' in s and 'install system to disk' not in s)
 elif a.action=='terminal':
  call('click','--label','Terminal');wait('active-desktop-terminal',lambda s:'node@bitcoin-core-node' in s)
 elif a.action=='set-password':
  call('click','--label','Settings');wait('node-settings',lambda s:'bitcoin core service' in s)
  call('click','--label','Login');wait('login-settings',lambda s:'require a password' in s and 'repeat password' in s)
  call('click','--label','Require');call('key','--keys','tab');type_text('NodeFixture-2026!\tNodeFixture-2026!\t');call('key','--keys','ret')
  wait('password-enabled',lambda s:'password login is enabled for the next login' in s)
 elif a.action=='phase':
  wait('active-desktop-terminal',lambda s:'node@bitcoin-core-node' in s)
  assert a.usb and a.phase and a.usb.is_file() and a.usb.absolute().is_relative_to(Path.home()/'node-v1-validation')
  call('usb-attach','--usb',str(a.usb.absolute()));type_text('clear\nudisksctl mount -b /dev/sda\n');time.sleep(2)
  media='/media/node/NODE_TEST';token=''.join(secrets.choice('2347') for _ in range(16))
  guest=('installed_gui_probe.py' if a.phase.startswith('gui-') else 'installed_power_probe.py' if a.phase.startswith('power-') else 'installed_onboarding_probe.py')
  type_text('NODE_VM_ACCEPTANCE=1 python3 '+media+'/'+guest+' '+a.phase+' --media '+media+' >'+media+'/onboarding-'+a.phase+'.log 2>&1; r=$?; sync; udisksctl unmount -b /dev/sda; u=$?; echo RESULT_'+token+'_${r}_UNMOUNT_${u}\n')
  pattern='result_'+token+r'[_ ]+([0-9o@]+)[_ ]+unmount[_ ]+([0-9o@]+)'
  result=re.search(pattern,wait('phase-'+a.phase,lambda s:re.search(pattern,s),authenticate=True))
  assert int(result[2].replace('o','0').replace('@','0'))==0,'Guest media unmount did not complete; leaving attached'
  call('usb-detach')
  for name in ['onboarding-'+a.phase+'.log','onboarding-'+a.phase+'-result.json']:
   fresh=root/(token+'-'+name);subprocess.run(['mcopy','-i',str(a.usb),'::'+name,str(fresh)],check=True,stdin=subprocess.DEVNULL,capture_output=True);fresh.replace(root/name)
  assert int(result[1].replace('o','0').replace('@','0'))==0,(root/('onboarding-'+a.phase+'.log')).read_text()
  report['check']=json.loads((root/('onboarding-'+a.phase+'-result.json')).read_text());assert report['check']['status']=='passed-covered-checks'
 report['status']='passed'
except Exception as e:report.update(status='failed',error=repr(e));raise
finally:(root/('onboarding-host-'+a.action+('-'+a.phase if a.phase else '')+'.json')).write_text(json.dumps(report,indent=2)+'\n')
