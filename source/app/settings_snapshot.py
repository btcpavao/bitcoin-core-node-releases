"""Versioned portable settings, mandatory GPG encryption, never a system image.

Root broker only. External I/O is performed as the authenticated desktop user.
The payload is semantic JSON, not an archive of paths, scripts or system files.
Imports are staged for early next boot: no live network or wallet is modified.
"""
from __future__ import annotations
import configparser
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import resource
import stat
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from chain_backup import identity, external, DIR_FLAGS, FILE_FLAGS, regular_at, Events
from gpg_backend import encrypt_file, decrypt_file, GPGError, _tmpfs
from network import wireguard, core_config, firewall
from state import DATA, CONFIG, load_setup, validate_setup

FORMAT = 'bitcoin-core-node-settings'
MAX_PAYLOAD = 4 * 1024 * 1024
MAX_FILE = 256 * 1024
STATE = Path('/var/lib/core-node-settings')
NM_DIR = Path('/etc/NetworkManager/system-connections')
ENV = dict(PATH='/usr/sbin:/usr/bin:/sbin:/bin', LANG='C.UTF-8', LC_ALL='C.UTF-8')
CORE_LIMITS = {'prune': (0, 2**31-1), 'dbcache': (4, 16384), 'par': (-256, 256),
               'maxmempool': (5, 100000), 'mempoolexpiry': (1, 100000),
               'maxconnections': (0, 4096), 'maxuploadtarget': (0, 2**31-1)}
GUI_BOOLS = {'fCoinControlFeatures', 'enable_psbt_controls', 'fMinimizeToTray',
             'fMinimizeOnClose', 'fHideTrayIcon', 'fUseEmbeddedMonospacedFont'}
EXCLUSIONS = ('Wallets, keys, PSBTs and blockchain data',
              'Login password, users and disk encryption',
              'Bluetooth pairing keys (pair again on the new adapter)',
              'Disk UUIDs, device paths, hardware identities and display positions',
              'Arbitrary scripts, third-party VPN plug-ins and external certificate files')

class SettingsError(RuntimeError): pass

def require(condition, message='Invalid or unsupported settings backup.'):
    if not condition: raise SettingsError(message)

def object_fields(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys))

def text(value, limit=256):
    require(isinstance(value, str) and len(value.encode('utf-8')) <= limit
            and not any(ord(c)<32 or ord(c)==127 for c in value))
    return value

def json_load(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result, 'Duplicate field in settings backup.')
            result[key]=value
        return result
    require(len(raw) <= MAX_PAYLOAD)
    try: return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(SettingsError('Invalid number.')))
    except (ValueError, UnicodeError, RecursionError):
        raise SettingsError('Invalid settings document.') from None

def canonical(data):
    return (json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(',',':'))+'\n').encode()

def safe_read(path, limit=MAX_FILE, *, owner=None, optional=False):
    path=Path(path)
    for parent in path.parents:
        require(not parent.is_symlink(), 'A configuration directory is a symbolic link.')
    try: fd=os.open(path, FILE_FLAGS)
    except FileNotFoundError:
        if optional:return None
        raise SettingsError('A required configuration file is missing.') from None
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=limit,
                'Unsafe or oversized configuration file.')
        if owner is not None:
            require(info.st_uid==owner and not info.st_mode & 0o022, 'Unsafe configuration file ownership.')
        raw=stream.read(limit+1)
        require(len(raw)<=limit)
        after=os.fstat(stream.fileno())
        require((info.st_size,info.st_mtime_ns,info.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns), 'A setting changed while it was being read. Please close other settings dialogs and retry.')
        return raw

def nm_profile(raw):
    """Parse with libnm; remove physical bindings, reject external executables/files."""
    import gi
    gi.require_version('NM','1.0')
    from gi.repository import NM, GLib
    require(isinstance(raw,str) and len(raw.encode())<=MAX_FILE and '\x00' not in raw)
    kf=GLib.KeyFile()
    try:
        kf.load_from_data(raw,len(raw.encode()),GLib.KeyFileFlags.NONE)
        groups=kf.get_groups()[0]
        if 'proxy' in groups:
            keys=kf.get_keys('proxy')[0]
            require(set(keys)<={'method'} and (not keys or kf.get_string('proxy','method') in ('0','none')), 'Proxy PAC scripts are not portable settings.')
            kf.remove_group('proxy');groups=kf.get_groups()[0]
        require(set(groups)<={'connection','wifi','wifi-security','ethernet','ipv4','ipv6',
                              '802-11-wireless','802-11-wireless-security','802-3-ethernet'},
                'This saved connection requires a nonportable or unsupported setting.')
        kind=kf.get_string('connection','type')
        require(kind in ('wifi','ethernet','802-11-wireless','802-3-ethernet'),
                'Only saved Wi-Fi and Ethernet profiles are portable here.')
        name=kf.get_string('connection','id');text(name)
        require(name, 'Saved connection has no name.')
        ident=str(uuid.UUID(kf.get_string('connection','uuid')))
        kf.set_string('connection','uuid',ident)
        # Do not copy adapter identities, host-specific access or dependencies.
        for group,keys in {
            'connection':('interface-name','permissions','stable-id','timestamp','master','controller','slave-type','port-type','secondaries','autoconnect-slaves','autoconnect-ports'),
            'wifi':('mac-address','bssid','seen-bssids','mac-address-blacklist','mac-address-denylist'),
            '802-11-wireless':('mac-address','bssid','seen-bssids','mac-address-blacklist','mac-address-denylist'),
            'ethernet':('mac-address','mac-address-blacklist','mac-address-denylist'),
            '802-3-ethernet':('mac-address','mac-address-blacklist','mac-address-denylist'),
        }.items():
            if group not in groups:continue
            for key in keys:
                if key in kf.get_keys(group)[0]:kf.remove_key(group,key)
        for group in ('wifi','802-11-wireless','ethernet','802-3-ethernet'):
            if group in groups and 'cloned-mac-address' in kf.get_keys(group)[0]:
                if kf.get_string(group,'cloned-mac-address') not in ('random','stable','permanent','preserve','stable-ssid'):
                    kf.remove_key(group,'cloned-mac-address')
        for group in ('wifi-security','802-11-wireless-security'):
            if group in groups and 'psk' in kf.get_keys(group)[0]:
                kf.set_integer(group,'psk-flags',0)
        connection=NM.keyfile_read(kf,'/etc/NetworkManager/system-connections',NM.KeyfileHandlerFlags.NONE,None,None)
        ok,_=connection.normalize(None);require(ok)
        require(connection.verify() and connection.verify_secrets())
        # Routing/IP settings are declarative. No arbitrary VPN plug-in, PAC,
        # EAP certificate path, dispatcher or shell command is imported.
        output=NM.keyfile_write(connection,NM.KeyfileHandlerFlags.NONE,None,None)
        if output.has_group('proxy') and not output.get_keys('proxy')[0]:output.remove_group('proxy')
        result=output.to_data()[0]
        sec=connection.get_setting_wireless_security()
        needs_secret=bool(sec and sec.get_key_mgmt() in ('wpa-psk','sae') and not sec.get_psk())
        return dict(uuid=ident,type='wifi' if connection.get_connection_type()=='802-11-wireless' else 'ethernet',
                    keyfile=result,needs_secret=needs_secret)
    except SettingsError:raise
    except Exception:
        raise SettingsError('A saved network profile could not be validated.') from None

def numeric_preferences(settings):
    require(isinstance(settings,dict))
    result={}
    for name,value in settings.items():
        if name not in CORE_LIMITS:continue
        require(type(value) in (int,str) and re.fullmatch(r'-?\d{1,12}',str(value)))
        number=int(value);lo,hi=CORE_LIMITS[name]
        require(lo<=number<=hi and (name!='prune' or number in (0,1) or number>=550),
                'A Bitcoin Core preference is outside the portable range.')
        result[name]=str(number)
    return result

def validate(data):
    object_fields(data,('format','version','created_utc','core_version','node','wireguard','clock','keyboard',
                        'display_scale','pointer','core','core_gui','connections','not_included'))
    require(data['format']==FORMAT and type(data['version']) is int and data['version']==1)
    require(isinstance(data['created_utc'],str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',data['created_utc']))
    require(isinstance(data['core_version'],str) and re.fullmatch(r'32\.\d{1,3}(?:\.\d{1,3})?',data['core_version']))
    object_fields(data['node'],('profile','network','prune_mib','private_broadcast'))
    validate_setup(dict(version=1,confirmed=True,data_uuid=None,**data['node']))
    if data['wireguard'] is not None:
        data['wireguard']=wireguard(data['wireguard'])[0]
    require(data['node']['profile']!='wireguard' or data['wireguard'] is not None,
            'The WireGuard privacy profile has no tunnel configuration.')
    object_fields(data['clock'],('timezone','automatic'))
    from system_time import zone
    zone(data['clock']['timezone']);require(type(data['clock']['automatic']) is bool)
    object_fields(data['keyboard'],('XKBMODEL','XKBLAYOUT','XKBVARIANT','XKBOPTIONS'))
    for key,value in data['keyboard'].items():
        require(isinstance(value,str) and len(value)<=256 and re.fullmatch(r'[A-Za-z0-9_,:+.-]*',value))
    require(data['keyboard']['XKBLAYOUT'], 'Keyboard layout is missing.')
    scale=data['display_scale']
    require(scale in ('auto','1','1.0','1.25','1.5','1.75','2','2.0'), 'Unsupported display scale.')
    require(isinstance(data['pointer'],dict) and len(data['pointer'])<=32)
    for name,speed in data['pointer'].items():
        require(text(name,200) and type(speed) in (int,float) and math.isfinite(speed) and -1<=speed<=1)
    require(isinstance(data['core'],dict) and not set(data['core'])-CORE_LIMITS.keys())
    data['core']=numeric_preferences(data['core'])
    require(isinstance(data['core_gui'],dict) and set(data['core_gui'])<=GUI_BOOLS|{'language'})
    for key,value in data['core_gui'].items():
        if key in GUI_BOOLS:require(value in ('true','false'))
        else:require(isinstance(value,str) and re.fullmatch(r'[A-Za-z_@.-]{0,32}',value))
    require(isinstance(data['connections'],list) and len(data['connections'])<=100)
    profiles=[];seen=set()
    for entry in data['connections']:
        object_fields(entry,('uuid','type','keyfile','needs_secret'))
        normalized=nm_profile(entry['keyfile'])
        require(normalized['uuid']==entry['uuid'] and normalized['type']==entry['type'] and
                type(entry['needs_secret']) is bool and normalized['needs_secret']==entry['needs_secret'])
        require(entry['uuid'] not in seen, 'Duplicate saved network.')
        seen.add(entry['uuid']);profiles.append(normalized)
    data['connections']=profiles
    require(isinstance(data['not_included'],list) and len(data['not_included'])<=64)
    for notice in data['not_included']:text(notice,300)
    return data

def gui_values(raw):
    result={};section=''
    for line in raw.decode('utf-8').splitlines():
        line=line.strip()
        if line.startswith('['):section=line
        elif section=='[General]' and '=' in line:
            name,value=line.split('=',1)
            if name in GUI_BOOLS and value in ('true','false'):result[name]=value
            elif name=='language' and re.fullmatch(r'[A-Za-z_@.-]{0,32}',value):result[name]=value
    return result

def collect():
    from system_time import snapshot
    from upgrades import active_release
    account=pwd.getpwnam('node');core=pwd.getpwnam('bitcoinnode')
    setup=load_setup();clock=snapshot();notices=list(EXCLUSIONS)
    raw=safe_read('/etc/default/keyboard',owner=0).decode('utf-8')
    keyboard={'XKBMODEL':'pc105','XKBLAYOUT':'us','XKBVARIANT':'','XKBOPTIONS':''}
    for line in raw.splitlines():
        m=re.fullmatch(r'\s*(XKBMODEL|XKBLAYOUT|XKBVARIANT|XKBOPTIONS)=["\']?([A-Za-z0-9_,:+.\-]*)["\']?\s*',line)
        if m:keyboard[m[1]]=m[2]
    scale=(safe_read('/etc/core-display-scale.conf',owner=0,optional=True) or b'auto').decode().strip()
    pointer_raw=safe_read('/home/node/.config/bitcoin-core-node/pointer.json',owner=account.pw_uid,optional=True)
    pointer=json_load(pointer_raw).get('devices',{}) if pointer_raw else {}
    settings=safe_read(DATA/'settings.json',owner=core.pw_uid,optional=True)
    preferences=numeric_preferences(json_load(settings) if settings else {})
    custom=safe_read(DATA/'bitcoin.conf',owner=core.pw_uid,optional=True)
    ignored=0
    section=''
    if custom:
        # Never carry arbitrary Core configuration, include paths or hooks.
        for line in custom.decode('utf-8').splitlines():
            line=line.split('#',1)[0].strip()
            if not line:continue
            if line.startswith('[') and line.endswith(']'):
                section=line[1:-1];continue
            if section not in ('',setup['network']):continue
            if '=' in line and line.split('=',1)[0].strip() in CORE_LIMITS:
                k,v=map(str.strip,line.split('=',1));preferences.update(numeric_preferences({k:v}))
            else:ignored+=1
    if ignored:notices.append('Custom Bitcoin configuration outside supported numeric preferences is not copied.')
    suffix='' if setup['network']=='main' else '-'+setup['network']
    raw=safe_read('/var/lib/bitcoin-core-node/gui/.config/Bitcoin/Bitcoin-Qt'+suffix+'.conf',owner=core.pw_uid,optional=True)
    profiles=[];skipped=0
    require(not NM_DIR.is_symlink())
    for path in sorted(NM_DIR.glob('*')):
        if path.name.startswith('.') or not path.is_file():continue
        require(len(profiles)+skipped<100,'Too many saved network profiles.')
        try:
            profile=nm_profile(safe_read(path,owner=0).decode('utf-8'))
        except SettingsError:
            skipped+=1;continue
        profiles.append(profile)
    if skipped:notices.append(f'{skipped} network profile(s) use unsupported settings and were not copied.')
    if any(p['needs_secret'] for p in profiles):notices.append('Some network passwords are not stored in the system profile; those will need to be entered again.')
    wg=safe_read('/etc/wireguard/core-node.conf',owner=0,optional=True)
    data=dict(format=FORMAT,version=1,created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
              core_version=active_release()['version'],node={k:setup[k] for k in ('profile','network','prune_mib','private_broadcast')},
              wireguard=wg.decode('utf-8') if wg else None,clock={k:clock[k] for k in ('timezone','automatic')},
              keyboard=keyboard,display_scale=scale,pointer=pointer,core=preferences,
              core_gui=gui_values(raw) if raw else {},connections=profiles,not_included=notices)
    return validate(data)

def summary(data):
    return dict(timezone=data['clock']['timezone'],automatic_time=data['clock']['automatic'],
                wifi=sum(p['type']=='wifi' for p in data['connections']),ethernet=sum(p['type']=='ethernet' for p in data['connections']),
                wireguard=data['wireguard'] is not None,privacy=data['node']['profile'],
                keyboard=data['keyboard']['XKBLAYOUT'],created_utc=data['created_utc'],
                not_included=data['not_included'],restart_required=True)

CORE_FORMAT = 'bitcoin-core-node-core-settings'

def validate_core(data):
    object_fields(data,('format','version','created_utc','core_version','network','core','core_gui','not_included'))
    require(data['format']==CORE_FORMAT and type(data['version']) is int and data['version']==1)
    require(isinstance(data['created_utc'],str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',data['created_utc']))
    require(isinstance(data['core_version'],str) and re.fullmatch(r'32\.\d{1,3}(?:\.\d{1,3})?',data['core_version']))
    require(data['network'] in ('main','regtest','signet'))
    require(isinstance(data['core'],dict) and not set(data['core'])-CORE_LIMITS.keys())
    data['core']=numeric_preferences(data['core'])
    require(isinstance(data['core_gui'],dict) and set(data['core_gui'])<=GUI_BOOLS|{'language'})
    for name,value in data['core_gui'].items():
        if name in GUI_BOOLS:require(value in ('true','false'))
        else:require(isinstance(value,str) and re.fullmatch(r'[A-Za-z_@.-]{0,32}',value))
    require(isinstance(data['not_included'],list) and len(data['not_included'])<=64)
    for value in data['not_included']:text(value,300)
    return data

def validate_any(data):
    require(isinstance(data,dict))
    return validate_core(data) if data.get('format')==CORE_FORMAT else validate(data)

def collect_core():
    from upgrades import active_release
    owner=pwd.getpwnam('bitcoinnode').pw_uid;network=load_setup()['network']
    raw=safe_read(DATA/'settings.json',owner=owner,optional=True)
    core=numeric_preferences(json_load(raw) if raw else {})
    conf=safe_read(DATA/'bitcoin.conf',owner=owner,optional=True) or b''
    section='';ignored=0
    for line in conf.decode('utf-8').splitlines():
        line=line.split('#',1)[0].strip()
        if not line:continue
        if line.startswith('[') and line.endswith(']'):section=line[1:-1];continue
        if section not in ('',network):continue
        if '=' in line and line.split('=',1)[0].strip() in CORE_LIMITS:
            k,v=map(str.strip,line.split('=',1));core.update(numeric_preferences({k:v}))
        else:ignored+=1
    suffix='' if network=='main' else '-'+network
    raw=safe_read('/var/lib/bitcoin-core-node/gui/.config/Bitcoin/Bitcoin-Qt'+suffix+'.conf',owner=owner,optional=True)
    omitted=['Wallets, descriptors, signing keys and wallet registrations',
             'Blockchain databases, host-specific paths and disk identity',
             'Wi-Fi passwords, VPN keys and operating system settings',
             'Executable hooks, includes and unsupported custom Core options']
    if ignored:omitted.append(f'{ignored} custom configuration line(s) were not portable and are not included.')
    return validate_core(dict(format=CORE_FORMAT,version=1,created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                 core_version=active_release()['version'],network=network,core=core,
                 core_gui=gui_values(raw) if raw else {},not_included=omitted))

def summary_any(data):
    if data.get('format')!=CORE_FORMAT:return summary(data)
    return dict(scope='core',created_utc=data['created_utc'],network=data['network'],
                options=sorted(data['core']),gui_options=sorted(data['core_gui']),
                not_included=data['not_included'],restart_required=True)

@contextmanager
def ram_work():
    # This Node is intentionally swap-free. Do not spill decrypted network keys.
    require(len(Path('/proc/swaps').read_text().splitlines())<=1, 'Disable swap before backing up or restoring secret settings.')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    with tempfile.TemporaryDirectory(prefix='core-node-settings-',dir='/run') as tmp:
        p=Path(tmp);os.chmod(p,0o700)
        fd=os.open(p,DIR_FLAGS)
        try:_tmpfs(fd)
        finally:os.close(fd)
        yield p

def save_encrypted(directory,secret,caller,events,*,core_only=False):
    # Historical API name retained for existing callers; empty passphrase means
    # an explicitly unencrypted checksum-protected JSON export.
    import encrypted_transfer as transfer
    events.update('Collecting portable settings',force=True)
    data=collect_core() if core_only else collect()
    name=transfer.publish(canonical(data),directory,secret,caller,events,
            prefix='bitcoin-core-config' if core_only else 'bitcoin-node-settings',limit=MAX_PAYLOAD)
    return dict(ok=True,directory=str(Path(name).parent),file=name,encrypted=bool(secret),summary=summary_any(data))

def read_encrypted(filename,secret,caller,events):
    import encrypted_transfer as transfer
    raw,fingerprint=transfer.read(filename,secret,caller,events,limit=MAX_PAYLOAD)
    return validate_any(json_load(raw)),fingerprint

def ensure_state():
    require(not STATE.is_symlink())
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=STATE.stat();require(info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o700,'Unsafe settings state directory.')

def atomic_private(path,data):
    raw=canonical(data)
    require(len(raw)<=16*1024*1024)
    fd,tmp=tempfile.mkstemp(prefix='.settings-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),0o600);stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
        fd=os.open(path.parent,DIR_FLAGS)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:Path(tmp).unlink(missing_ok=True)

def perform(action,request,caller,events):
    require(os.geteuid()==0 and caller==pwd.getpwnam('node').pw_uid and (CONFIG/'installed').is_file(),
            'Settings transfer requires the installed local Node desktop.')
    core_only=action.startswith('core-settings-')
    if core_only:action=action.removeprefix('core-')
    pending_name='pending-core.json' if core_only else 'pending.json'
    require(action in ('settings-backup','settings-preview','settings-import','settings-cancel','settings-status'))
    ensure_state()
    if action in ('settings-cancel','settings-status'):
        require(request=={})
        if action=='settings-cancel':
            (STATE/pending_name).unlink(missing_ok=True)
            fd=os.open(STATE,DIR_FLAGS)
            try:os.fsync(fd)
            finally:os.close(fd)
        pending=safe_read(STATE/pending_name,MAX_PAYLOAD,owner=0,optional=True)
        result=safe_read(STATE/'result.json',MAX_PAYLOAD,owner=0,optional=True)
        return dict(ok=True,pending=bool(pending),last_result=json_load(result) if result else None)
    keys={'path','passphrase'}|({'confirmed','fingerprint'} if action=='settings-import' else set())
    object_fields(request,keys)
    secret=request['passphrase'];require(isinstance(secret,str) and len(secret)<=512)
    require(isinstance(request['path'],str) and len(request['path'])<=4096)
    if action=='settings-backup':return save_encrypted(request['path'],secret,caller,events,core_only=core_only)
    data,fingerprint=read_encrypted(request['path'],secret,caller,events)
    require((data['format']==CORE_FORMAT)==core_only,'Please open this backup through its matching configuration category.')
    from upgrades import active_release
    require(data['core_version']==active_release()['version'],'Use the same Bitcoin Core version to restore these settings.')
    require((data.get('network') if core_only else data['node']['network'])==load_setup()['network'],'This backup uses a different Bitcoin network. No settings were changed.')
    if action=='settings-preview':return dict(ok=True,summary=summary_any(data),fingerprint=fingerprint)
    require(request['confirmed'] is True and request['fingerprint']==fingerprint,'Backup changed after preview. Please review it again.')
    require(not (STATE/'rollback.json').exists(),'A previous settings transaction needs recovery before another import.')
    events.check();events.cancel_allowed=False
    atomic_private(STATE/pending_name,data)
    return dict(ok=True,staged=True,summary=summary_any(data),restart_required=True)
