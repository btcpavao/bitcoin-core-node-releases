"""USB/external destination discovery. Never guesses a disk path or uses a shell.

Enumerate USB-backed filesystems through lsblk and mount only a user-selected
filesystem with udisksctl (Polkit, local logged-in user). No partitioning,
formatting or raw block writes are performed.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import getpass

LSBLK='/usr/bin/lsblk'
UDISKS='/usr/bin/udisksctl'
LSBLK_ARGS=('-J','-b','-o','NAME,PATH,TYPE,TRAN,RM,RO,LABEL,FSTYPE,SIZE,MOUNTPOINTS,PKNAME,UUID')
NODE_USER='node'
FILESYSTEMS=frozenset(('ext4','ext3','ext2','btrfs','xfs','exfat','vfat','ntfs','ntfs3'))
BLOCK_PATH=re.compile(r'^/dev/(?:sd[a-z][0-9]{0,3}|nvme[0-9]+n[0-9]+p[0-9]+|mmcblk[0-9]+p[0-9]+|dm-[0-9]+|mapper/[A-Za-z0-9_.+-]+)$')

class DriveError(ValueError):
    pass

def safe_mount(path,user=None):
    if not isinstance(path,str) or not path.startswith('/') or len(path)>4096:
        return None
    user=user or getpass.getuser()
    candidate=Path(path)
    if not candidate.is_dir():return None
    try: resolved=candidate.resolve(strict=True)
    except (ValueError,OSError):return None
    # A leftover empty /media/node/USB directory is not an attached drive.
    # Never turn unplugged removable storage into a backup on the root disk.
    if not resolved.is_mount():return None
    # Only external-user mount points. Generic /run is volatile workspace;
    # /boot/efi, /, the live USB root, and Core's own data are never targets.
    roots=(Path('/media')/user,Path('/run/media')/user)
    if not any(root in resolved.parents for root in roots):
        return None
    return resolved

def parse_lsblk(raw,user=None):
    try:
        tree=json.loads(raw)['blockdevices']
        if not isinstance(tree,list):raise ValueError()
    except (TypeError,ValueError,KeyError) as exc:
        raise DriveError('USB device information is unavailable.') from exc
    matches=[]
    def walk(dev,usb=False):
        if not isinstance(dev,dict):return
        usb=bool(usb or str(dev.get('tran') or '').lower()=='usb' or dev.get('rm') is True or dev.get('rm')==1)
        name=dev.get('path')
        filesystem=str(dev.get('fstype') or '').lower()
        kind=dev.get('type')
        if (usb and kind in ('part','disk','crypt') and isinstance(name,str)
            and BLOCK_PATH.fullmatch(name) and filesystem in FILESYSTEMS):
            raw_mounts=dev.get('mountpoints') or []
            if not isinstance(raw_mounts,list):raw_mounts=[]
            mounted=next((str(p) for m in raw_mounts if m
                          if (p:=safe_mount(m,user)) is not None),None)
            value=dict(path=name,label=str(dev.get('label') or dev.get('name') or 'USB storage')[:100],
                       fstype=filesystem,bytes=int(dev.get('size') or 0),
                       read_only=bool(dev.get('ro')),mount=mounted,
                       uuid=str(dev.get('uuid') or '')[:128])
            matches.append(value)
        for child in dev.get('children') or []:
            walk(child,usb)
    for dev in tree:walk(dev)
    # One filesystem entry per physical partition. Never present internal EFI.
    seen=set();unique=[]
    for item in matches:
        if item['path'] not in seen:
            seen.add(item['path']);unique.append(item)
    return sorted(unique,key=lambda x:(not bool(x['mount']),x['label'].casefold(),x['path']))

def list_drives():
    try:
        result=subprocess.run([LSBLK,*LSBLK_ARGS],capture_output=True,text=True,timeout=9)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise DriveError('USB discovery did not respond. Please reconnect the disk and try Refresh.') from exc
    if result.returncode:
        raise DriveError('Unable to list USB drives. Try reconnecting the disk.')
    return parse_lsblk(result.stdout)

def is_selected_drive(entry,latest):
    return (isinstance(entry,dict) and isinstance(latest,dict)
            and latest['path']==entry.get('path')
            and latest['fstype']==entry.get('fstype')
            and latest['uuid']==entry.get('uuid')
            and latest['bytes']==entry.get('bytes')
            and latest['label']==entry.get('label'))

def recheck_drive(entry):
    return next((dev for dev in list_drives() if is_selected_drive(entry,dev)),None)
