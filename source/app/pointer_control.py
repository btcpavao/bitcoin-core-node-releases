"""Unprivileged XInput/libinput mouse speed controls and hotplug persistence.

No root permissions, shell invocation, or changes to Core; Bluetooth and USB
pointer devices are matched by the OS-provided XInput name at X session start.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

XINPUT='/usr/bin/xinput'
PREFS=Path.home()/'.config/bitcoin-core-node/pointer.json'
DEVICE=re.compile(r'(?P<name>.*?)\s+id=(?P<id>\d+)\s+\[slave\s+pointer\s+\(\d+\)\]')
ACCEL=re.compile(r'^\s*libinput Accel Speed \(\d+\):\s*(-?(?:\d+(?:\.\d*)?|\.\d+))\s*$')

class PointerError(ValueError):
    pass

def xinput(*args):
    try:
        p=subprocess.run([XINPUT,*map(str,args)],capture_output=True,text=True,timeout=7,
                          env={k:v for k,v in os.environ.items()
                               if k in ('DISPLAY','XAUTHORITY','HOME','LANG','LC_ALL','XDG_RUNTIME_DIR','PATH')})
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise PointerError('Mouse settings cannot reach the local X display. Please check the current session.') from exc
    if p.returncode:
        raise PointerError('The pointer device is unavailable. Reconnect it, then click Refresh.')
    return p.stdout

def get_devices():
    result=[]
    for line in xinput('--list','--short').splitlines():
        found=DEVICE.search(line)
        if not found:continue
        name=found['name'].lstrip('⎜⎡⎣⎢⎟↳ ').strip()
        if not name or len(name)>200 or any(ord(c)<32 or ord(c)==127 for c in name):continue
        device_id=int(found['id'])
        if device_id<=0:continue
        try:
            speed=read_speed(device_id)
        except PointerError:
            continue  # Virtual or special pointer without a libinput speed property.
        if speed is not None:
            result.append(dict(id=device_id,name=name,speed=speed))
    return result

def read_speed(device_id):
    if not isinstance(device_id,int) or device_id<=0:raise PointerError('Invalid pointer device.')
    for line in xinput('--list-props',device_id).splitlines():
        found=ACCEL.fullmatch(line)
        if found:
            speed=float(found[1])
            if -1<=speed<=1:return speed
    return None

def set_speed(device_id,speed):
    if not isinstance(device_id,int) or not 1<=device_id<=65535:
        raise PointerError('Invalid pointer device.')
    if not isinstance(speed,(int,float)) or not -1.0<=speed<=1.0:
        raise PointerError('Pointer speed must be between -1 and +1.')
    xinput('--set-prop',device_id,'libinput Accel Speed',f'{speed:.2f}')

def load_preferences():
    try:
        if PREFS.is_symlink():raise ValueError('Invalid mouse preference file.')
        data=PREFS.read_bytes()
        if len(data)>8192:raise ValueError('Oversized mouse preferences.')
        parsed=json.loads(data)
        if not isinstance(parsed,dict) or parsed.get('schema')!=1:raise ValueError()
        return {k:round(float(v),2) for k,v in parsed.get('devices',{}).items()
                if isinstance(k,str) and 1<=len(k)<=200 and isinstance(v,(int,float))
                and -1<=v<=1}
    except (OSError,ValueError,TypeError,OverflowError):
        return {}

def save_preference(name,speed):
    if not isinstance(name,str) or not 1<=len(name)<=200 or any(ord(c)<32 or ord(c)==127 for c in name):
        raise PointerError('Invalid pointer name.')
    if not isinstance(speed,(int,float)) or not -1<=speed<=1:raise PointerError('Invalid pointer speed.')
    parent=PREFS.parent
    parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if parent.is_symlink() or PREFS.is_symlink():
        raise PointerError('Mouse preferences must not be symbolic links.')
    data=load_preferences()
    data[name]=round(float(speed),2)
    fd,tmp=tempfile.mkstemp(prefix='.pointer-',dir=parent)
    try:
        with os.fdopen(fd,'w') as output:
            os.fchmod(output.fileno(),0o600)
            json.dump(dict(schema=1,devices=data),output,sort_keys=True)
            output.write('\n');output.flush();os.fsync(output.fileno())
        os.replace(tmp,PREFS)
    finally:
        Path(tmp).unlink(missing_ok=True)

def watch():
    # This runs as the regular desktop user, never as root. USB/Bluetooth
    # hotplug and subsequent X11 sessions reapply only explicit saved choices.
    while True:
        try:
            prefs=load_preferences()
            if prefs:
                for item in get_devices():
                    target=prefs.get(item['name'])
                    if target is not None and abs(target-item['speed'])>0.03:
                        try:set_speed(item['id'],target)
                        except PointerError:pass
        except PointerError:pass
        time.sleep(5)

if __name__=='__main__':
    import sys
    if sys.argv[1:]==['--watch']:watch()
    else:raise SystemExit('Use --watch.')
