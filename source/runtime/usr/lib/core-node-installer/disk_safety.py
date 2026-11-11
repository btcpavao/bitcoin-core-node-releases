#!/usr/bin/python3
"""Read-only disk eligibility/identity check. Does not partition or unmount."""
from __future__ import annotations
import json, os, re, stat, subprocess, sys
from pathlib import Path

MIN_BYTES = 32 * 1024**3
class UnsafeDisk(ValueError): pass

def walk(node):
    yield node
    for child in node.get('children', []): yield from walk(child)

def flag(value):
    return value is True or str(value).lower() in ('1','true','yes')

def validate_tree(node, syspath, holders, active_swaps):
    name = node.get('name', '')
    if not re.fullmatch(r'/dev/(?:sd[a-z]+|hd[a-z]+|nvme\d+n\d+|vd[a-z]+)', name):
        raise UnsafeDisk('Only whole internal SATA/NVMe or virtual test disks are supported.')
    if node.get('type') != 'disk': raise UnsafeDisk('Not a whole disk.')
    if flag(node.get('ro')) or flag(node.get('rm')): raise UnsafeDisk('Read-only or removable device.')
    transport = (node.get('tran') or '').lower()
    if transport in ('usb','mmc','firewire','iscsi','fc') or re.search(r'/usb\d*(?:/|$)', syspath):
        raise UnsafeDisk('External/removable/network storage is not an installation target.')
    if int(node.get('size',0)) < MIN_BYTES: raise UnsafeDisk('Disk must be at least 32 GiB.')
    if not ((node.get('serial') or '').strip() or (node.get('wwn') or '').strip()):
        raise UnsafeDisk('No stable serial/WWN was reported; refusing an ambiguous disk.')
    for child in walk(node):
        if child.get('type') not in ('disk','part'):
            raise UnsafeDisk('Active LVM, RAID or mapped storage is not supported.')
        if any(p for p in (child.get('mountpoints') or [])):
            raise UnsafeDisk('Disk or a partition is mounted. No automatic unmount is performed.')
        if child.get('name') in active_swaps:
            raise UnsafeDisk('Disk has active swap.')
        if child.get('name') in holders:
            raise UnsafeDisk('Disk/partition is held by another block device.')
    return {
        'name': name, 'size': int(node['size']),
        'major_minor': node.get('maj:min',''),
        'serial': (node.get('serial') or '').strip(),
        'wwn': (node.get('wwn') or '').strip(),
        'model': (node.get('model') or '').strip(), 'sysfs': syspath,
    }

def probe(device):
    if not re.fullmatch(r'/dev/[A-Za-z0-9]+', device): raise UnsafeDisk('Invalid device path.')
    st = os.stat(device)
    if not stat.S_ISBLK(st.st_mode): raise UnsafeDisk('Not a block device.')
    p=subprocess.run(['/usr/bin/lsblk','--json','--bytes','--paths','--output',
       'NAME,KNAME,TYPE,TRAN,RO,RM,SIZE,MOUNTPOINTS,SERIAL,WWN,MODEL,MAJ:MIN',device],
       check=True, capture_output=True, text=True, timeout=10,
       env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'})
    nodes=json.loads(p.stdout)['blockdevices']
    if len(nodes)!=1: raise UnsafeDisk('Ambiguous lsblk result.')
    node=nodes[0]
    syspath=str((Path('/sys/class/block')/Path(device).name).resolve(strict=True))
    holders=set()
    for n in walk(node):
        k=Path(n['name']).name
        h=Path('/sys/class/block')/k/'holders'
        if not h.is_dir(): raise UnsafeDisk('Cannot inspect device holders.')
        if any(h.iterdir()): holders.add(n['name'])
    swaps={line.split()[0] for line in Path('/proc/swaps').read_text().splitlines()[1:] if line.split()}
    result=validate_tree(node,syspath,holders,swaps)
    if not Path('/sys/firmware/efi').is_dir() and result['size'] > 2 * 1024**4:
        raise UnsafeDisk('For a drive larger than 2 TiB, restart this installer in UEFI mode.')
    if result['major_minor'] != f'{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}':
        raise UnsafeDisk('Device identity changed during inspection.')
    return result

if __name__=='__main__':
    try:
        if len(sys.argv)!=3 or sys.argv[1]!='probe': raise UnsafeDisk('Usage: disk_safety.py probe /dev/DISK')
        print(json.dumps(probe(sys.argv[2]),sort_keys=True,separators=(',',':')))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
        print(f'Core Node: {e}',file=sys.stderr);sys.exit(1)
