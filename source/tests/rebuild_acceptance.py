#!/usr/bin/python3
"""Repeat native install, real reboot and network checks on the DNS-fixed ISO."""
from pathlib import Path
import argparse,os,subprocess,time
p=argparse.ArgumentParser();p.add_argument("--firmware",choices=["bios","uefi"]);p.add_argument("--resume-graphical",action="store_true");args=p.parse_args()
repo=Path(__file__).resolve().parents[1];base=Path.home()/'node-v1-validation'
art=base/'82c2301/bitcoin-core-node-development-82c2301e1d8f86e6962583bc5072a866ac6f411d'
iso=art/'bitcoin-core-node-development-amd64.iso'
env=os.environ.copy();env['PATH']=str(base/'bin')+':'+env['PATH']
def call(script,*args,log=None):
 r=subprocess.run(['python3',str(repo/'tests'/script),*map(str,args)],cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT)
 assert r.returncode==0,(script,r.returncode)
for _ in range(60):
 if (art/'SHA256SUMS').exists() and subprocess.run(['sha256sum','-c','SHA256SUMS'],cwd=art,capture_output=True).returncode==0:break
 time.sleep(30)
else:raise RuntimeError('Verified ISO download not available')
for firmware in ([args.firmware] if args.firmware else ['bios','uefi']):
 root=base/(firmware+'-82c2301');media=base/(firmware+'-82c2301-public.img')
 if not args.resume_graphical:
  assert not root.exists() and not media.exists()
  call('prepare_vm_media.py','--output',media,'--core-bin',base/'core/bitcoin-32.1/bin')
  subprocess.run(['mcopy','-i',str(media),str(repo/'tests/installed_network_probe.py'),'::installed_network_probe.py'],check=True)
  call('vm_probe.py','start','--root',root,'--iso',iso,*(['--uefi'] if firmware=='uefi' else []))
 with (root/'acceptance-host.log').open('w') as log:
  if not args.resume_graphical:call('install_vm.py','--root',root,log=log)
  call('boot_vm.py','--root',root,'--usb',media,'--keep-running',*(['--resume','graphical'] if args.resume_graphical else []),log=log)
  call('boot_vm.py','--root',root,'--usb',media,'--resume','root','--extra','network',log=log)
 print('PASSED '+firmware+' exact-image install, reboot, resolver and network',flush=True)
