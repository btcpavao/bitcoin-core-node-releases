#!/usr/bin/python3
"""Drive the actual installed Node/live Vault pair through removable USB."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

p=argparse.ArgumentParser()
p.add_argument('--node',type=Path,required=True)
p.add_argument('--vault',type=Path,required=True)
p.add_argument('--usb',type=Path,required=True)
p.add_argument('--resume',choices=['all','export','create','sign','broadcast','cleanup'],default='all')
p.add_argument('--until',choices=['export','create','sign','broadcast','cleanup'],default='cleanup')
a=p.parse_args()
probe=Path(__file__).with_name('vm_probe.py')
report={'checks':[],'screens':[],'usb':str(a.usb)}

class VM:
    def __init__(self,root,vault=False):
        self.root=root;self.vault=vault
        record=json.loads((root/'fixture.json').read_text())
        assert record['command'][record['command'].index('-nic')+1]=='none'
        assert root.is_relative_to(Path.home()/'node-v1-validation')
        report['vault_iso' if vault else 'node_iso']=record['iso']
    def call(self,action,*options):
        return subprocess.run(['python3',str(probe),action,'--root',str(self.root),*options],
            capture_output=True,text=True,check=True,timeout=120).stdout.strip()
    def type(self,text):self.call('type','--text',text)
    def screen(self):
        path=self.call('screen')
        text=subprocess.run(['tesseract',path,'stdout','--psm','6'],capture_output=True,text=True,check=True).stdout.lower().replace('?','')
        return path,text
    def wait(self,label,predicate,timeout=240):
        end=time.monotonic()+timeout;last=0
        while time.monotonic()<end:
            path,text=self.screen()
            if predicate(text):
                report['screens'].append({'label':label,'path':path})
                print('Observed '+label,flush=True);return text
            if time.monotonic()-last>30:
                print('Waiting '+label,flush=True);last=time.monotonic()
            time.sleep(2)
        raise RuntimeError('Deadline '+label+': '+text)
    def phase(self,name):
        self.type('clear\n')
        self.call('usb-attach','--usb',str(a.usb))
        if self.vault:
            time.sleep(3)
            self.type('udisksctl mount -b /dev/sda\n')
            media='/media/vault/NODE_TEST'
        else:
            self.type('mkdir -p /mnt/node-test; mount LABEL=NODE_TEST /mnt/node-test\n')
            media='/mnt/node-test'
        while True:
            token=''.join(secrets.choice('2347') for _ in range(12))
            try:
                (self.root/('token-'+token)).touch(exist_ok=False);break
            except FileExistsError:pass
        command='NODE_VM_ACCEPTANCE=1 python3 '+media+'/installed_exchange_probe.py '+name+' --media '+media
        release='udisksctl unmount -b /dev/sda' if self.vault else 'umount '+media
        self.type(command+' >'+media+'/exchange-'+name+'.log 2>&1; r=$?; sync; '+release+'; u=$?; echo EXCHANGE_'+token+'_${r}_UNMOUNT_${u}\n')
        pattern='exchange[_ ]+'+token+r'[_ ]+([0-9o@]+)[_ ]+unmount[_ ]+([0-9o@]+)'
        text=self.wait(name,lambda s:re.search(pattern,s) is not None,360)
        match=re.search(pattern,text)
        assert match[2].replace('o','0').replace('@','0')=='0','Media is not confirmed unmounted'
        self.call('usb-detach')
        paths={}
        for name2 in ['exchange-'+name+'.log','exchange-'+name+'-result.json']:
            target=self.root/(token+'-'+name2)
            subprocess.run(['mcopy','-i',str(a.usb),'::'+name2,str(target)],check=True,
                capture_output=True,stdin=subprocess.DEVNULL,timeout=30)
            paths[name2]=target
        assert match[1].replace('o','0').replace('@','0')=='0',paths['exchange-'+name+'.log'].read_text()
        result=json.loads(paths['exchange-'+name+'-result.json'].read_text())
        assert result['status']=='passed-covered-checks'
        report['checks'].append(result);print(json.dumps(result),flush=True)

node=VM(a.node);vault=VM(a.vault,True)
phases=[('export',vault),('create',node),('sign',vault),('broadcast',node),('cleanup',vault)]
try:
    start=0 if a.resume=='all' else [x[0] for x in phases].index(a.resume)
    stop=[x[0] for x in phases].index(a.until)+1
    for name,vm in phases[start:stop]:vm.phase(name)
    report['status']='passed-covered-checks'
finally:
    (a.node/('exchange-acceptance-'+str(time.time_ns())+'.json')).write_text(json.dumps(report,indent=2)+'\n')
