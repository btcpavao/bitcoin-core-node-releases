"""Bounded keyboard/mouse preferences for the local X11 desktop.

Only apply_system_layout runs under the existing fixed Node helper. All repeat,
Num Lock and libinput controls run as the desktop account; no shell commands.
"""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

import pointer_control as pointer

PREFS = Path.home()/'.config/bitcoin-core-node/input.json'
CATALOG = Path('/usr/share/X11/xkb/rules/evdev.xml')
KEYBOARD = Path('/etc/default/keyboard')
XORG = Path('/etc/X11/xorg.conf.d/90-core-node-keyboard.conf')
MAX_BYTES = 32768
DEFAULTS = dict(schema=1, keyboard=dict(repeat=True, delay_ms=500, rate_hz=25, numlock=True), devices={})
BOOL_PROPS = {
 'left_handed': 'libinput Left Handed Enabled',
 'natural_scroll': 'libinput Natural Scrolling Enabled',
 'tap_to_click': 'libinput Tapping Enabled',
 'disable_while_typing': 'libinput Disable While Typing Enabled',
 'middle_emulation': 'libinput Middle Emulation Enabled',
}

class InputError(ValueError):
    pass


def require(test, message='Please check the keyboard and mouse settings.'):
    if not test: raise InputError(message)


def catalog(path=CATALOG):
    tree=ET.parse(path).getroot()
    layouts={}
    for item in tree.findall('./layoutList/layout'):
        name=item.findtext('configItem/name');description=item.findtext('configItem/description') or name
        variants={'': 'Default'}
        for variant in item.findall('./variantList/variant'):
            variants[variant.findtext('configItem/name')]=variant.findtext('configItem/description') or variant.findtext('configItem/name')
        layouts[name]=dict(description=description, variants=variants)
    models={n.findtext('configItem/name'): n.findtext('configItem/description') for n in tree.findall('./modelList/model')}
    options={n.findtext('configItem/name') for n in tree.findall('./optionList/group/option')}
    return layouts,models,options


def validate_layout(data):
    require(isinstance(data,dict) and set(data)=={'model','layout','variant','options'})
    require(all(isinstance(v,str) and len(v)<=256 and re.fullmatch(r'[A-Za-z0-9_,:+.-]*',v) for v in data.values()))
    layouts,models,options=catalog()
    require(data['model'] in models, 'Please choose a listed keyboard model.')
    require(data['layout'] in layouts, 'Please choose a listed keyboard layout.')
    require(data['variant'] in layouts[data['layout']]['variants'], 'Please choose a variant for that layout.')
    requested=data['options'].split(',') if data['options'] else []
    require(len(requested)<=16 and set(requested)<=options, 'The keyboard options are not supported by this system.')
    return dict(data)


def read_system_layout(path=KEYBOARD):
    result=dict(model='pc105',layout='us',variant='',options='')
    names={'XKBMODEL':'model','XKBLAYOUT':'layout','XKBVARIANT':'variant','XKBOPTIONS':'options'}
    try:
        for line in path.read_text().splitlines():
            m=re.fullmatch(r'\s*(XKBMODEL|XKBLAYOUT|XKBVARIANT|XKBOPTIONS)=["\']?([A-Za-z0-9_,:+.\-]*)["\']?\s*',line)
            if m:result[names[m[1]]]=m[2]
    except OSError:pass
    return result


def xorg_text(data):
    data=validate_layout(data)
    return ('# Managed keyboard layout; applies to the login screen after restart.\n'
            'Section "InputClass"\n    Identifier "Bitcoin Core Node keyboard"\n'
            '    MatchIsKeyboard "on"\n'+''.join(
                f'    Option "{name}" "{data[key]}"\n' for name,key in (
                    ('XkbModel','model'),('XkbLayout','layout'),('XkbVariant','variant'),('XkbOptions','options')))+'EndSection\n')


def atomic(path,raw,mode=0o600):
    require(not path.is_symlink(),'A settings file must not be a symbolic link.')
    # Fixed or account-owned paths only; do not traverse symlinked directories.
    for p in path.parents:
        require(not p.is_symlink(),'A settings folder must not be a symbolic link.')
    existed=path.parent.exists()
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700 if mode==0o600 else 0o755)
    if not existed:path.parent.chmod(0o700 if mode==0o600 else 0o755)
    if path.exists():
        info=path.stat();require(stat.S_ISREG(info.st_mode) and info.st_uid==os.geteuid(),'Unexpected settings-file ownership.')
    fd,tmp=tempfile.mkstemp(prefix='.input-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            os.fchmod(out.fileno(),mode);out.write(raw);out.flush();os.fsync(out.fileno())
        os.replace(tmp,path)
    finally:Path(tmp).unlink(missing_ok=True)


def apply_system_layout(request):
    require(os.geteuid()==0,'Keyboard layout saving requires the Node settings helper.')
    data=validate_layout(request)
    before={p:p.read_bytes() if p.exists() and not p.is_symlink() else None for p in (KEYBOARD,XORG)}
    require(not KEYBOARD.is_symlink() and not XORG.is_symlink(),'A system keyboard file is a symbolic link.')
    raw=(''.join(f'{name}="{data[key]}"\n' for name,key in (
        ('XKBMODEL','model'),('XKBLAYOUT','layout'),('XKBVARIANT','variant'),('XKBOPTIONS','options')))+'BACKSPACE="guess"\n').encode()
    try:
        atomic(KEYBOARD,raw,0o644);atomic(XORG,xorg_text(data).encode(),0o644)
    except Exception:
        for p,old in before.items():
            if old is None:p.unlink(missing_ok=True)
            else:atomic(p,old,0o644)
        raise
    return dict(ok=True,keyboard=data)


def validate(data):
    require(isinstance(data,dict) and set(data)=={'schema','keyboard','devices'} and type(data['schema']) is int and data['schema']==1)
    k=data['keyboard']
    require(isinstance(k,dict) and set(k)=={'repeat','delay_ms','rate_hz','numlock'})
    require(type(k['repeat']) is bool and type(k['numlock']) is bool)
    require(type(k['delay_ms']) is int and 100<=k['delay_ms']<=2000)
    require(type(k['rate_hz']) is int and 1<=k['rate_hz']<=60)
    require(isinstance(data['devices'],dict) and len(data['devices'])<=32)
    for name,settings in data['devices'].items():
        require(isinstance(name,str) and 1<=len(name)<=200 and not any(ord(c)<32 or ord(c)==127 for c in name))
        require(isinstance(settings,dict) and set(settings)<=set(BOOL_PROPS)|{'acceleration','scroll_method'})
        for key,value in settings.items():
            if key in BOOL_PROPS:require(type(value) is bool)
            elif key=='acceleration':require(value in ('adaptive','flat'))
            elif key=='scroll_method':require(value in ('two_finger','edge','button'))
    return copy.deepcopy(data)


def load(path=None):
    path=PREFS if path is None else Path(path)
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as src:
            info=os.fstat(src.fileno());require(stat.S_ISREG(info.st_mode) and info.st_size<=MAX_BYTES)
            raw=src.read(MAX_BYTES+1);require(len(raw)<=MAX_BYTES)
        return validate(json.loads(raw))
    except (OSError,ValueError,TypeError):return copy.deepcopy(DEFAULTS)


def save(data,path=None):
    data=validate(data);path=PREFS if path is None else Path(path)
    atomic(path,(json.dumps(data,sort_keys=True)+'\n').encode())
    from home_backup import remember_local_use
    remember_local_use()


def run(command):
    try:result=subprocess.run(command,capture_output=True,text=True,timeout=5)
    except (OSError,subprocess.SubprocessError) as exc:raise InputError('The desktop input service is unavailable. Please try again.') from exc
    if result.returncode:raise InputError('The input device could not apply this setting. Please reconnect it and refresh the device list.')
    return result.stdout


def apply_keyboard(data,*,layout=None,numlock=True):
    k=validate(dict(schema=1,keyboard=data,devices={}))['keyboard']
    if layout is not None:
        l=validate_layout(layout)
        run(['/usr/bin/setxkbmap','-model',l['model'],'-layout',l['layout'],'-variant',l['variant'],'-option','', '-option',l['options']])
    if k['repeat']:
        run(['/usr/bin/xset','r','on']);run(['/usr/bin/xset','r','rate',str(k['delay_ms']),str(k['rate_hz'])])
    else:run(['/usr/bin/xset','r','off'])
    if numlock:run(['/usr/local/bin/core-node-numlock','on' if k['numlock'] else 'off'])


def properties(device_id):
    require(type(device_id) is int and 1<=device_id<=65535)
    result={}
    for line in pointer.xinput('--list-props',device_id).splitlines():
        m=re.fullmatch(r'\s*(libinput [^\(]+) \(\d+\):\s*(.*?)\s*',line)
        if m:
            try:result[m[1]]=tuple(float(x.strip()) for x in m[2].split(','))
            except ValueError:pass
    return result


def device_choices(props):
    result={key:bool(props[prop][0]) for key,prop in BOOL_PROPS.items() if prop in props and len(props[prop])==1}
    for key,available,enabled,labels in (
       ('acceleration','libinput Accel Profiles Available','libinput Accel Profile Enabled',('adaptive','flat')),
       ('scroll_method','libinput Scroll Methods Available','libinput Scroll Method Enabled',('two_finger','edge','button'))):
        avail=props.get(available,());active=props.get(enabled,())
        opts=[label for i,label in enumerate(labels) if i<len(avail) and avail[i]==1]
        if opts:
            result[key]=dict(available=opts,value=next((label for i,label in enumerate(labels) if i<len(active) and active[i]==1),opts[0]))
    return result


def apply_device(device_id,settings):
    validate(dict(schema=1,keyboard=DEFAULTS['keyboard'],devices={'device':settings}))
    props=properties(device_id)
    for key,value in settings.items():
        if key in BOOL_PROPS:
            prop=BOOL_PROPS[key]
            if prop in props and props[prop]!=(int(value),):pointer.xinput('--set-prop',device_id,prop,str(int(value)))
        else:
            prefix='libinput Accel Profile' if key=='acceleration' else 'libinput Scroll Method'
            labels=('adaptive','flat') if key=='acceleration' else ('two_finger','edge','button')
            available=props.get('libinput Accel Profiles Available' if key=='acceleration' else 'libinput Scroll Methods Available',())
            enabled=props.get(prefix+' Enabled',())
            index=labels.index(value)
            if index>=len(available) or not available[index] or not enabled:continue
            vector=tuple(int(i==index) for i in range(len(enabled)))
            if enabled!=vector:pointer.xinput('--set-prop',device_id,prefix+' Enabled',*vector)


def watch():
    last_keyboard=None;first=True
    while True:
        try:
            data=load()
            # Do not keep forcing Num Lock after the user presses it manually.
            if first or data['keyboard']!=last_keyboard:
                try:
                    apply_keyboard(data['keyboard'],numlock=True)
                    last_keyboard=data['keyboard'];first=False
                except InputError:pass  # A keyboard without Num Lock cannot block mouse hotplug.
            old_speeds=pointer.load_preferences()
            if old_speeds or data['devices']:
                for d in pointer.get_devices():
                    speed=old_speeds.get(d['name'])
                    if speed is not None and abs(d['speed']-speed)>.03:pointer.set_speed(d['id'],speed)
                    if d['name'] in data['devices']:apply_device(d['id'],data['devices'][d['name']])
        except (OSError,ValueError,subprocess.SubprocessError):pass
        time.sleep(5)

if __name__=='__main__':
    import sys
    if sys.argv[1:]==['--watch']:watch()
    else:raise SystemExit('Use --watch.')
