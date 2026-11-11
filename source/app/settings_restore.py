"""Early-boot application of validated semantic settings with durable rollback.

Never consumes caller paths. Root-only fixed helper runs before network/Core.
Imported network credentials may be staged root-only, like system NM profiles;
portable USB backups remain encrypted. No login, wallet or blockchain writes.
"""
import base64
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import tempfile

import settings_snapshot as ss
from state import DATA, load_setup

FIXED = {
 'etc/bitcoin-core-node/setup.json','etc/bitcoin-core-node/bitcoin.conf',
 'etc/bitcoin-core-node/firewall.nft','etc/bitcoin-core-node/restored-time.json',
 'etc/wireguard/core-node.conf','etc/default/keyboard','etc/core-display-scale.conf',
 'etc/timezone','etc/localtime','home/node/.config/bitcoin-core-node/pointer.json',
 'home/node/.config/bitcoin-core-node/input.json','etc/X11/xorg.conf.d/90-core-node-keyboard.conf',
 'var/lib/bitcoin-core-node/data/settings.json','var/lib/bitcoin-core-node/data/bitcoin.conf',
 'var/lib/bitcoin-core-node/gui/.config/Bitcoin/Bitcoin-Qt.conf',
 'var/lib/bitcoin-core-node/gui/.config/Bitcoin/Bitcoin-Qt-regtest.conf',
 'var/lib/bitcoin-core-node/gui/.config/Bitcoin/Bitcoin-Qt-signet.conf',
}
NM_PREFIX='etc/NetworkManager/system-connections/'

def allowed(relative):
    if relative in FIXED:return True
    if relative.startswith(NM_PREFIX):
        name=relative[len(NM_PREFIX):]
        return (0<len(name.encode())<=255 and name not in ('.','..') and '/' not in name
                and not any(ord(c)<32 or ord(c)==127 for c in name) and not name.startswith('.'))
    return False

def target(root,relative):
    ss.require(allowed(relative),'Settings transaction contains an invalid target.')
    p=Path(root)/relative
    for parent in p.parents:
        if parent==Path(root):break
        ss.require(not parent.is_symlink(),'A settings target directory is a symbolic link.')
    return p

def file_record(body,uid=0,gid=0,mode=0o600):
    return dict(kind='file',data=base64.b64encode(body).decode(),uid=uid,gid=gid,mode=mode)

def read_old(root,relative):
    p=target(root,relative)
    try:info=p.lstat()
    except FileNotFoundError:return None
    if stat.S_ISLNK(info.st_mode):
        ss.require(relative=='etc/localtime','A configuration target is a symbolic link.')
        link=os.readlink(p)
        # Retain only the legitimate timezone symlink, never an arbitrary path.
        resolved=(p.parent/link).resolve()
        zones=(Path(root)/'usr/share/zoneinfo').resolve()
        ss.require(resolved.is_relative_to(zones),'Unsafe existing time-zone link.')
        return dict(kind='symlink',target=link,uid=info.st_uid,gid=info.st_gid,mode=0o777)
    raw=ss.safe_read(p,ss.MAX_PAYLOAD)
    ss.require(info.st_uid in (0,pwd.getpwnam('node').pw_uid,pwd.getpwnam('bitcoinnode').pw_uid)
               and not info.st_mode & 0o022,'Unsafe existing settings permissions.')
    return file_record(raw,info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))

def ensure_parents(root,p,uid,gid):
    missing=[];q=p.parent
    while q!=Path(root) and not q.exists():missing.append(q);q=q.parent
    for q in reversed(missing):
        q.mkdir(mode=0o700 if uid else 0o755)
        os.chown(q,uid,gid)

def write_record(root,relative,record):
    p=target(root,relative)
    if record is None:
        p.unlink(missing_ok=True)
        if p.parent.exists():sync(p.parent)
        return
    ss.require(isinstance(record,dict) and record.get('kind') in ('file','symlink'))
    uid,gid,mode=(record[k] for k in ('uid','gid','mode'))
    ss.require(type(uid) is int and type(gid) is int and type(mode) is int and 0<=mode<=0o777)
    ensure_parents(root,p,uid,gid)
    fd,tmp=tempfile.mkstemp(prefix='.settings-',dir=p.parent)
    try:
        if record['kind']=='symlink':
            ss.require(relative=='etc/localtime')
            os.close(fd);fd=None;os.unlink(tmp)
            destination=record['target'];ss.require(isinstance(destination,str))
            zones=(Path(root)/'usr/share/zoneinfo').resolve()
            resolved=(p.parent/destination).resolve()
            # Production absolute links are rooted at /; fixture links are relative.
            ss.require(resolved.is_relative_to(zones),'Unsafe time-zone link in rollback.')
            os.symlink(destination,tmp);os.lchown(tmp,uid,gid)
        else:
            raw=base64.b64decode(record['data'],validate=True)
            ss.require(len(raw)<=ss.MAX_PAYLOAD)
            with os.fdopen(fd,'wb') as stream:
                fd=None;os.fchown(stream.fileno(),uid,gid);os.fchmod(stream.fileno(),mode)
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,p);sync(p.parent)
    finally:
        if fd is not None:os.close(fd)
        Path(tmp).unlink(missing_ok=True)

def sync(path):
    fd=os.open(path,ss.DIR_FLAGS)
    try:os.fsync(fd)
    finally:os.close(fd)

def update_ini(raw,values):
    """Do not deserialize or rewrite target Qt @Variant values."""
    lines=raw.decode('utf-8').splitlines(keepends=True);out=[];general=False;found=set();has=False
    for line in lines:
        stripped=line.strip()
        if stripped.startswith('['):
            if general:
                for k in sorted(set(values)-found):out.append(k+'='+values[k]+'\n');found.add(k)
            general=stripped=='[General]';has=has or general
        if general and '=' in line:
            name=line.split('=',1)[0].strip()
            if name in values:
                if name not in found:out.append(name+'='+values[name]+'\n');found.add(name)
                continue
        out.append(line)
    if not has:out.append('\n[General]\n')
    elif not general and set(values)-found:
        out.append('\n[General]\n')
    elif out and not out[-1].endswith('\n'):out.append('\n')
    for k in sorted(set(values)-found):out.append(k+'='+values[k]+'\n')
    return ''.join(out).encode()

def core_plan(data,root,setup):
    core=pwd.getpwnam('bitcoinnode');plan={}
    old=ss.safe_read(root/'var/lib/bitcoin-core-node/data/settings.json',ss.MAX_PAYLOAD,owner=core.pw_uid,optional=True)
    settings=ss.json_load(old) if old else {};ss.require(isinstance(settings,dict))
    settings.update(data['core'])
    plan['var/lib/bitcoin-core-node/data/settings.json']=file_record(ss.canonical(settings),core.pw_uid,core.pw_gid)
    confpath=root/'var/lib/bitcoin-core-node/data/bitcoin.conf'
    conf=(ss.safe_read(confpath,owner=core.pw_uid,optional=True) or b'').decode()
    # Update only supported numeric options; wallet registrations stay untouched.
    kept=[];section=''
    for line in conf.splitlines(keepends=True):
        stripped=line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):section=stripped[1:-1]
        if section in ('',setup['network']) and line.split('=',1)[0].strip() in data['core']:continue
        kept.append(line)
    conf='# Portable preferences restored by Bitcoin Core Node.\n'+''.join(k+'='+v+'\n' for k,v in data['core'].items())+'\n'+''.join(kept)
    plan['var/lib/bitcoin-core-node/data/bitcoin.conf']=file_record(conf.encode(),core.pw_uid,core.pw_gid)
    suffix='' if setup['network']=='main' else '-'+setup['network']
    relative='var/lib/bitcoin-core-node/gui/.config/Bitcoin/Bitcoin-Qt'+suffix+'.conf'
    raw=ss.safe_read(root/relative,owner=core.pw_uid,optional=True) or b'[General]\n'
    plan[relative]=file_record(update_ini(raw,data['core_gui']),core.pw_uid,core.pw_gid)
    return plan

def build_plan(data,root=Path('/')):
    data=ss.validate_any(data)
    if data['format']==ss.CORE_FORMAT:
        setup=load_setup(Path(root)/'etc/bitcoin-core-node/setup.json')
        ss.require(data['network']==setup['network'],'Bitcoin network differs; no configuration was imported.')
        return core_plan(data,Path(root),setup)
    root=Path(root);node=pwd.getpwnam('node');core=pwd.getpwnam('bitcoinnode')
    setup=load_setup(root/'etc/bitcoin-core-node/setup.json')
    ss.require(data['node']['network']==setup['network'],'Bitcoin network differs; no configuration was imported.')
    # Hardware storage remains the target's own. Regenerate firewall for its UID.
    setup.update(data['node'])
    tunnel=endpoint=port=None
    if data['wireguard'] is not None:tunnel,endpoint,port=ss.wireguard(data['wireguard'])
    plan={
        'etc/bitcoin-core-node/setup.json':file_record(ss.canonical(setup),mode=0o644),
        'etc/bitcoin-core-node/bitcoin.conf':file_record(ss.core_config(setup).encode(),mode=0o644),
        'etc/bitcoin-core-node/firewall.nft':file_record(ss.firewall(setup['profile'],core.pw_uid,endpoint,port).encode(),mode=0o644),
        'etc/bitcoin-core-node/restored-time.json':file_record(ss.canonical(data['clock'])),
        'etc/wireguard/core-node.conf':file_record(tunnel.encode()) if tunnel else None,
        'etc/default/keyboard':file_record((''.join(k+'="'+v+'"\n' for k,v in data['keyboard'].items())+'BACKSPACE="guess"\n').encode(),mode=0o644),
        'etc/core-display-scale.conf':file_record((data['display_scale']+'\n').encode(),mode=0o644),
        'etc/timezone':file_record((data['clock']['timezone']+'\n').encode(),mode=0o644),
        'etc/localtime':dict(kind='symlink',target='../usr/share/zoneinfo/'+data['clock']['timezone'],uid=0,gid=0,mode=0o777),
        'home/node/.config/bitcoin-core-node/pointer.json':file_record(ss.canonical(dict(schema=1,devices=data['pointer'])),node.pw_uid,node.pw_gid),
    }
    from desktop_input import xorg_text
    kb=data['keyboard']
    # Old multi-layout profiles still restore through Debian's existing path.
    if ',' not in kb['XKBLAYOUT']:
        plan['etc/X11/xorg.conf.d/90-core-node-keyboard.conf']=file_record(xorg_text(dict(model=kb['XKBMODEL'],layout=kb['XKBLAYOUT'],variant=kb['XKBVARIANT'],options=kb['XKBOPTIONS'])).encode(),mode=0o644)
    else:plan['etc/X11/xorg.conf.d/90-core-node-keyboard.conf']=None
    if data['version']==2:
        plan['home/node/.config/bitcoin-core-node/input.json']=file_record(ss.canonical(data['input']),node.pw_uid,node.pw_gid)
    plan.update(core_plan(data,root,setup))
    existing={}
    parent=root/NM_PREFIX
    ss.require(not parent.is_symlink())
    for path in sorted(parent.glob('*')):
        if path.name.startswith('.') or not path.is_file():continue
        try:
            p=ss.nm_profile(ss.safe_read(path,owner=0).decode())
        except ss.SettingsError:continue
        existing.setdefault(p['uuid'],[]).append(path.name)
    for p in data['connections']:
        # Merge by UUID, remove duplicate instances of that UUID only.
        filename='core-node-restored-'+p['uuid']+'.nmconnection'
        output=parent/filename
        if output.exists():
            current=ss.nm_profile(ss.safe_read(output,owner=0).decode())
            ss.require(current['uuid']==p['uuid'],'A network profile filename conflicts with an unrelated connection.')
        for old in existing.get(p['uuid'],[]):
            if old!=filename:plan[NM_PREFIX+old]=None
        plan[NM_PREFIX+filename]=file_record(p['keyfile'].encode())
    return plan

def recover(state=ss.STATE,root=Path('/')):
    path=state/'rollback.json'
    raw=ss.safe_read(path,16*1024*1024,owner=0,optional=True)
    if raw is None:return
    data=json.loads(raw)
    ss.require(isinstance(data,dict) and set(data)=={'version','phase','previous'} and data['version']==1)
    ss.require(data['phase'] in ('applying','committed') and isinstance(data['previous'],dict) and len(data['previous'])<=220)
    # Validate all destinations before any write, including a recovery retry.
    for relative in data['previous']:target(root,relative)
    if data['phase']=='applying':
        for relative,record in data['previous'].items():write_record(root,relative,record)
    path.unlink();sync(state)

def _apply_one(state=ss.STATE,root=Path('/'),pending_name='pending.json'):
    state=Path(state);root=Path(root)
    if not state.exists():return
    ss.require(state.is_dir() and not state.is_symlink() and state.stat().st_uid==0 and stat.S_IMODE(state.stat().st_mode)==0o700)
    # An interrupted change is rolled back before reading a pending request again.
    recover(state,root)
    pending=state/pending_name
    raw=ss.safe_read(pending,ss.MAX_PAYLOAD,owner=0,optional=True)
    if raw is None:return
    committed=False
    try:
        data=ss.validate_any(ss.json_load(raw))
        from upgrades import active_release
        ss.require(data['core_version']==active_release()['version'],'Core version changed after settings were staged.')
        plan=build_plan(data,root)
        previous={relative:read_old(root,relative) for relative in plan}
        journal=dict(version=1,phase='applying',previous=previous)
        ss.atomic_private(state/'rollback.json',journal)
        try:
            for relative,record in plan.items():write_record(root,relative,record)
            journal['phase']='committed';ss.atomic_private(state/'rollback.json',journal);committed=True
        except BaseException:
            recover(state,root);raise
        pending.unlink();sync(state)
        recover(state,root)
        ss.atomic_private(state/'result.json',dict(ok=True,message='Portable settings were restored. Login credentials and wallets were preserved.',summary=ss.summary_any(data)))
    except Exception:
        if committed:
            raise ss.SettingsError('Settings were applied but completion bookkeeping failed. Networking remains blocked until recovery succeeds.') from None
        # Never print a serialized connection or source exception containing keys.
        recover(state,root)
        pending.unlink(missing_ok=True);sync(state)
        ss.atomic_private(state/'result.json',dict(ok=False,message='Settings import could not be applied. Previous settings were retained. Review compatibility and try again.'))
        raise ss.SettingsError('Settings restore was refused; previous settings were retained.') from None

def apply_pending(state=ss.STATE,root=Path('/')):
    # Whole-Node settings first; an explicitly staged Core-only restore follows.
    _apply_one(state,root,'pending.json')
    _apply_one(state,root,'pending-core.json')

def apply_time():
    path=Path('/etc/bitcoin-core-node/restored-time.json')
    raw=ss.safe_read(path,4096,owner=0,optional=True)
    if raw is None:return
    data=ss.json_load(raw);ss.object_fields(data,('timezone','automatic'))
    from system_time import zone,runctl
    zone(data['timezone']);ss.require(type(data['automatic']) is bool)
    # No historic wall-clock value is restored. NTP runs after D-Bus is available.
    runctl('set-timezone',data['timezone']);runctl('set-ntp','true' if data['automatic'] else 'false')
    path.unlink();sync(path.parent)
