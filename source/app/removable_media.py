"""Verified removable-file access for Core; no raw block-device access.

Fixed root service; no caller-supplied commands/paths. Only supported, currently
mounted USB filesystems in /media/node or /run/media/node are considered. The
source is pinned by an open descriptor, matched to lsblk/findmnt device numbers,
and exposed through bindfs in the host namespace. Writable media supports file
creation as the desktop user; read-only mounts remain read-only. Only this
verified view root is added to Core's writable sandbox. Original ownership and
permissions of existing USB files are not changed.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import signal
import stat
import subprocess
import time
from usb_destinations import LSBLK, LSBLK_ARGS, parse_lsblk

ROOT = Path('/run/core-node-media')
ENV = dict(PATH='/usr/sbin:/usr/bin:/sbin:/bin', LANG='C.UTF-8', LC_ALL='C.UTF-8')


def core_in_use():
    result = subprocess.run(['/usr/bin/systemctl', 'is-active', 'bitcoin-core-node.service'],
                            env=ENV, capture_output=True, text=True, timeout=5)
    return result.stdout.strip() in ('active', 'activating', 'deactivating', 'reloading')


def records():
    raw = subprocess.check_output([LSBLK, *LSBLK_ARGS], env=ENV, timeout=10)
    return [d for d in parse_lsblk(raw.decode(), user='node') if d.get('mount')][:16]


def source_identity(entry):
    path = Path(entry['mount'])
    if path.is_symlink() or not path.is_mount() or path.resolve() != path:
        raise RuntimeError('Removable source is not a canonical mount.')
    rows = json.loads(subprocess.check_output(
        ['/usr/bin/findmnt','-J','-M',str(path),'-o','TARGET,SOURCE,FSTYPE,MAJ:MIN,ID,OPTIONS'],
        env=ENV, timeout=5))['filesystems']
    device = os.stat(entry['path'])
    info = path.stat()
    if not stat.S_ISBLK(device.st_mode) or len(rows) != 1:
        raise RuntimeError('Unexpected removable block device.')
    row = rows[0]
    source = str(row['source']).split('[',1)[0]
    backing = os.stat(source) if source.startswith('/dev/') else None
    allowed = {entry['fstype']}
    if entry['fstype'] in ('ntfs','ntfs3'):allowed.update(('ntfs3','fuseblk'))
    if (row['target'] != str(path) or row['fstype'] not in allowed
            or backing is None or not stat.S_ISBLK(backing.st_mode)
            or backing.st_rdev != device.st_rdev
            or row['maj:min'] != f'{os.major(info.st_dev)}:{os.minor(info.st_dev)}'):
        raise RuntimeError('Removable device identity did not match.')
    mount_id = int(row['id'])
    options = set(row['options'].split(','))
    readonly = bool(entry.get('read_only') or 'ro' in options or os.statvfs(path).f_flag & os.ST_RDONLY)
    # A fresh mount of the same UUID/device must not reuse an obsolete view.
    return (str(path), info.st_dev, info.st_ino, device.st_rdev,
            entry.get('uuid',''), entry['bytes'], mount_id, readonly)


def view_name(entry, identity):
    label = re.sub(r'[^A-Za-z0-9 ._()-]', '_', entry['label']).strip(' .')[:32] or 'USB'
    suffix = hashlib.sha256(repr(identity).encode()).hexdigest()[:8]
    return label+' ['+suffix+']'+(' (read-only)' if identity[-1] else '')


def prepare():
    if os.geteuid() != 0:
        raise RuntimeError('Removable views require the fixed system service.')
    if ROOT.is_symlink():
        raise RuntimeError('Unsafe removable view root.')
    ROOT.mkdir(mode=0o755, exist_ok=True)
    info = ROOT.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError('Unsafe removable view root.')
    # Remove only abandoned mounts with our exact root, type and source prefix.
    for p in ROOT.iterdir():
        if p.is_symlink():
            raise RuntimeError('Unexpected removable view link.')
        if p.is_mount():
            r = json.loads(subprocess.check_output(['/usr/bin/findmnt','-J','-M',str(p),'-o','TARGET,SOURCE,FSTYPE,OPTIONS'],timeout=5))['filesystems']
            if (len(r)!=1 or r[0]['target']!=str(p) or r[0]['fstype']!='fuse.bindfs'
                    or not re.fullmatch(r'.+ \[[a-f0-9]{8}\](?: \(read-only\))?',p.name)
                    or not re.fullmatch(r'(?:/proc/self/fd/[0-9]+|core-node-usb-[a-f0-9]{16})',r[0]['source'])
                    or not {'nodev','nosuid','noexec'}.issubset(r[0]['options'].split(','))):
                raise RuntimeError('Unrecognized mount in removable view root.')
            subprocess.run(['/usr/bin/fusermount3','-u','-z',str(p)],check=True,timeout=5)
        if p.is_dir():
            p.rmdir()  # Never recursive deletion and never on a mounted source.


def mount_arguments(fd, target, identity):
    readonly = identity[-1]
    token = hashlib.sha256(repr(identity).encode()).hexdigest()[:16]
    args = ['/usr/bin/bindfs', '-f', '--force-user=bitcoinnode',
            '--force-group=bitcoin-rpc',
            '--perms=0000:u=rD:g=rD' if readonly else '--perms=0000:u=rwD:g=rwD',
            '--create-for-user=node', '--create-for-group=node',
            '--create-with-perms=u+rwD', '--chmod-ignore', '--chown-deny',
            '--chgrp-deny', '--xattr-none']
    if readonly:
        args.append('-r')
    args += ['-o', 'nodev,nosuid,noexec,default_permissions,subtype=bindfs,fsname=core-node-usb-'+token,
             '/proc/self/fd/'+str(fd), str(target)]
    # Never resolve symlinks in the root helper and never enable device/ioctl
    # access. Core follows links only under its own existing sandbox.
    return args


class View:
    def __init__(self, entry, identity):
        self.identity = identity
        self.path = ROOT/view_name(entry, identity)
        self.process = None
        self.path.mkdir(mode=0o555)  # A disconnected view cannot become a writable disk folder.
        fd = os.open(entry['mount'],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if (info.st_dev,info.st_ino)!=(identity[1],identity[2]) or source_identity(entry)!=identity:
                raise RuntimeError('Removable source changed before exposure.')
            # Pin the exact mount, including mount ID, rather than a stale path.
            fdinfo = Path('/proc/self/fdinfo/'+str(fd)).read_text()
            actual_id = next(int(line.split(':',1)[1]) for line in fdinfo.splitlines() if line.startswith('mnt_id:'))
            if actual_id != identity[-2]:
                raise RuntimeError('Removable mount was replaced before exposure.')
            self.process = subprocess.Popen(mount_arguments(fd, self.path, identity),
                pass_fds=(fd,),env=ENV,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            deadline=time.monotonic()+5
            while not self.path.is_mount():
                if self.process.poll() is not None or time.monotonic()>deadline:
                    raise RuntimeError('Verified removable view could not start.')
                time.sleep(.04)
        except BaseException:
            self.close();raise
        finally:
            os.close(fd)

    def close(self):
        if self.path.is_mount():
            subprocess.run(['/usr/bin/fusermount3','-u','-z',str(self.path)],timeout=5,check=True)
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        if self.path.exists():self.path.rmdir()


def main():
    import sys
    if len(sys.argv)!=1:
        raise RuntimeError('This service accepts no path or operation arguments.')
    os.umask(0o022)
    pwd.getpwnam('node');pwd.getpwnam('bitcoinnode')
    prepare();views={};alive=True;last_errors=set()
    def stop(*_):
        nonlocal alive
        alive=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        while alive:
            desired={};errors=set()
            try:
                # Release pinned USB sources after Core closes, so Files can
                # unmount them normally. Desktop apps use the original mount.
                for entry in (records() if core_in_use() else []):
                    try:
                        identity=source_identity(entry)
                        desired[identity]=entry
                    except Exception:errors.add('A mounted USB filesystem could not be verified for the Core view.')
            except Exception:
                # No stale source is silently retained after failed discovery.
                errors.add('Removable device discovery is temporarily unavailable.')
            for identity in list(views):
                if identity not in desired or views[identity].process.poll() is not None:
                    views.pop(identity).close()
            for identity,entry in desired.items():
                if identity not in views:
                    try:views[identity]=View(entry,identity)
                    except Exception:errors.add('A verified USB could not be exposed to Core.')
            for error in errors-last_errors:print(error,flush=True)
            last_errors=errors
            time.sleep(2)
    finally:
        for view in views.values():view.close()


if __name__=='__main__':
    main()
