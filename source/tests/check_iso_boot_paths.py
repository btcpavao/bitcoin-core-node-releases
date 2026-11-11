#!/usr/bin/python3
"""Reject ISO boot entries pointing to a removed or renamed live kernel/initrd."""
import argparse
from pathlib import Path
import re
import shlex
import subprocess
import tempfile


def check_iso(iso):
    iso=Path(iso).resolve(strict=True)
    listing=subprocess.run(['xorriso','-indev',str(iso),'-find','/live',
                            '-type','f','-exec','lsdl'],check=True,capture_output=True,text=True)
    available=set()
    for line in listing.stdout.splitlines():
        fields=shlex.split(line)
        if fields and fields[-1].startswith('/live/'):
            available.add(fields[-1])
    if not available:
        raise RuntimeError('ISO live filesystem inventory is empty.')
    references=[]
    with tempfile.TemporaryDirectory(prefix='node-iso-boot-paths-') as td:
        for name in ('boot/grub/grub.cfg','isolinux/live.cfg'):
            target=Path(td)/Path(name).name
            subprocess.run(['xorriso','-osirrox','on','-indev',str(iso),
                            '-extract','/'+name,str(target)],check=True,capture_output=True)
            kinds=set()
            for line in target.read_text().splitlines():
                match=re.match(r'\s*(linux(?:efi)?|initrd(?:efi)?)\s+(/live/\S+)',line)
                if not match:continue
                kind,path=match.groups();kinds.add(kind.removesuffix('efi'))
                if path not in available:
                    raise RuntimeError(name+' references a missing boot file: '+path)
                references.append((name,path))
            if kinds!={'linux','initrd'}:
                raise RuntimeError(name+' does not contain both live kernel and initrd entries.')
    print('PASS BIOS/UEFI live boot paths ('+str(len(references))+' references)')
    return references


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--iso',required=True,type=Path)
    check_iso(parser.parse_args().iso)
