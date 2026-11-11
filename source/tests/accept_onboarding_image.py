#!/usr/bin/python3
"""Native install, automatic startup and real reboot for one verified ISO."""
import argparse,json,os,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--artifact',type=Path,required=True);p.add_argument('--firmware',choices=['bios','uefi'],required=True);a=p.parse_args()
base=Path.home()/'node-v1-validation';artifact=a.artifact.absolute();repo=Path(__file__).resolve().parents[1]
assert artifact.is_relative_to(base) and not artifact.is_symlink()
root=base/(a.firmware+'-'+artifact.name);media=base/(root.name+'-public.img')
env=os.environ.copy();env['PATH']=str(base/'bin')+':'+env['PATH']
for _ in range(180):
 if (artifact/'SHA256SUMS').exists() and subprocess.run(['sha256sum','-c','SHA256SUMS'],cwd=artifact,capture_output=True).returncode==0:break
 time.sleep(10)
else:raise RuntimeError('Verified ISO not downloaded')
assert not root.exists();assert media.is_file()
def call(script,*args):
 subprocess.run(['python3',str(repo/'tests'/script),*map(str,args)],env=env,check=True)
def action(name,*args):call('onboarding_vm.py',name,'--root',root,*args)
call('vm_probe.py','start','--root',root,'--iso',artifact/'bitcoin-core-node-development-amd64.iso',*(['--uefi'] if a.firmware=='uefi' else []))
call('install_vm.py','--root',root)
action('boot');action('terminal');action('phase','--usb',media,'--phase','before')
action('reboot');action('home');action('terminal');action('phase','--usb',media,'--phase','default-reboot')
action('poweroff')
record=json.loads((root/'fixture.json').read_text());proc=Path('/proc')/str(record['pid'])/'cmdline'
for _ in range(60):
 if not proc.exists() or str(root/'qmp.sock').encode() not in proc.read_bytes():break
 time.sleep(1)
else:raise RuntimeError('Owned VM did not finish graceful poweroff')
(root/'onboarding-acceptance.json').write_text(json.dumps({'status':'passed','source_iso':str(artifact/'bitcoin-core-node-development-amd64.iso'),'firmware':a.firmware,'checks':['native install without user/password form','automatic local login and mainnet Core startup','bounded administration and public wallet snapshot','actual reboot preserves automatic login and public wallet data','graceful poweroff']},indent=2)+'\n')
print('PASS exact '+a.firmware+' onboarding image acceptance',flush=True)
