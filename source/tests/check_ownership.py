#!/usr/bin/python3
"""Fail closed if privileged Node services lose reviewed numeric UID/GID/mode.

The reference is the verified Node 32.1 ISO from 2026-11-01.
Never loosen KPMcore/DBus policy as an installation workaround.
"""
from pathlib import Path
import argparse,json,re,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
BASELINE=ROOT/'tests/node-critical-ownership-debian13.json'

def verify(squashfs):
    p=Path(squashfs).resolve(strict=True)
    expected=json.loads(BASELINE.read_text())['required']
    cmd=['unsquashfs','-lln',str(p),*sorted(expected)]
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
    if result.returncode:
        raise RuntimeError('SquashFS numeric ownership inspection failed: '+result.stderr[-500:])
    found={}
    for line in result.stdout.splitlines():
        if 'squashfs-root/' not in line:continue
        m=re.match(r'^([dlcbps-][rwxstST-]{9})\s+(\d+)/(\d+)\s+',line)
        if m:
            name=line.split('squashfs-root/',1)[1].split(' -> ')[0]
            found[name]={'uid':int(m[2]),'gid':int(m[3]),'mode':m[1]}
    bad=[(k,v,found.get(k)) for k,v in expected.items() if found.get(k)!=v]
    if bad:raise RuntimeError('Node ownership/mode regression: '+repr(bad[:10]))
    helper=found['usr/lib/dbus-1.0/dbus-daemon-launch-helper']
    assert helper['mode']=='-rwsr-xr--',helper
    assert helper['gid']==990 and helper['uid']==0,helper
    print('NODE CRITICAL SQUASHFS UID/GID/MODE CHECK PASSED ('+str(len(expected))+' paths)')
    return len(expected)

def verify_iso(iso):
    with tempfile.TemporaryDirectory(prefix='node-ownership-iso-',dir='/tmp') as tmp:
        root=Path(tmp)
        subprocess.run(['xorriso','-osirrox','on','-indev',str(iso),'-extract',
                        '/live/filesystem.squashfs',str(root/'root.squashfs')],
                        check=True,capture_output=True)
        return verify(root/'root.squashfs')

if __name__=='__main__':
    a=argparse.ArgumentParser()
    options=a.add_mutually_exclusive_group(required=True)
    options.add_argument('--squashfs',type=Path)
    options.add_argument('--iso',type=Path)
    args=a.parse_args()
    verify(args.squashfs) if args.squashfs else verify_iso(args.iso)
