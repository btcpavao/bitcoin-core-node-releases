#!/usr/bin/python3
"""Offline four-file update for the tested 2026-11-05 Node hardware image.

Run from the generated bundle. Never installs an OS, copies chain data, opens a
wallet, changes a login or restarts a service. Restart Node normally afterwards
so already-running GUI processes load the updated dialog modules.
"""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

FILES = ('chain_backup.py', 'chain_probe.py', 'chain_ui.py', 'usb_dialog.py')
TARGET = Path('/usr/lib/bitcoin-core-node')
RECORD = Path('/var/lib/bitcoin-core-node/maintenance/chain-backup-20261106')
LOCKS = ('/run/lock/bitcoin-core-node-admin.lock', '/run/lock/core-node-software.lock')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def trusted(path, directory=False):
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
            or (not directory and info.st_nlink != 1)):
        raise RuntimeError('Unsafe installed path: ' + str(path))
    return info


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, data, mode=0o644):
    fd, name = tempfile.mkstemp(prefix='.chain-update-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    if os.geteuid() != 0 or sys.argv[1:] not in ([], ['--check']):
        raise RuntimeError('Please run: sudo python3 install.py [--check] on the installed Bitcoin Core Node.')
    check_only = sys.argv[1:] == ['--check']
    trusted(Path('/etc/bitcoin-core-node/installed'))
    trusted(TARGET, directory=True)
    if TARGET.resolve() != TARGET:
        raise RuntimeError('The installed application directory must not be a symbolic link.')
    bundle = Path(__file__).resolve().parent
    metadata = json.loads((bundle / 'manifest.json').read_bytes())
    if metadata.get('format') != 'core-node-chain-fix-20261106' or set(metadata.get('files', {})) != set(FILES):
        raise RuntimeError('Invalid update manifest.')
    payload = {}
    for name in FILES:
        content = (bundle / 'files' / name).read_bytes()
        if digest(content) != metadata['files'][name]['new_sha256']:
            raise RuntimeError('Update payload checksum mismatch: ' + name)
        compile(content, name, 'exec')
        payload[name] = content
    with contextlib.ExitStack() as stack:
        for path in LOCKS:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
                raise RuntimeError('Unsafe maintenance lock.')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('A Node operation or software update is active. Please finish it before applying this update.') from None
        for unit in ('core-node-software-check.service', 'core-node-software-install.service'):
            result = subprocess.run(['/usr/bin/systemctl', 'is-active', '--quiet', unit], timeout=10)
            if result.returncode == 0:
                raise RuntimeError('Software maintenance is active. Please finish it before applying this update.')
        original = {}
        for name in FILES:
            path = TARGET / name
            trusted(path)
            original[name] = path.read_bytes()
            allowed = metadata['files'][name]
            if digest(original[name]) not in (allowed['base_sha256'], allowed['new_sha256']):
                raise RuntimeError('This Node has a different revision of ' + name + '. No files were changed.')
        if check_only:
            print('CHECK PASSED: installed Node and all four update files match the expected versions. No files changed.')
            return
        if all(original[name] == payload[name] for name in FILES):
            print('This fix is already installed. Please restart the computer normally to reload any open dialogs.')
            return
        parent = RECORD.parent
        trusted(parent.parent, directory=True)
        parent.mkdir(mode=0o700, exist_ok=True)
        trusted(parent, directory=True)
        RECORD.mkdir(mode=0o700, exist_ok=True)
        trusted(RECORD, directory=True)
        for name, content in original.items():
            backup = RECORD / (name + '.previous')
            if not backup.exists():
                atomic_write(backup, content, 0o600)
            else:
                trusted(backup)
                if digest(backup.read_bytes()) not in (metadata['files'][name]['base_sha256'], metadata['files'][name]['new_sha256']):
                    raise RuntimeError('Unexpected earlier update backup. No application files were changed.')
        status = {'source_commit': metadata['source_commit'], 'state': 'applying', 'files': list(FILES)}
        atomic_write(RECORD / 'status.json', (json.dumps(status, indent=2) + '\n').encode(), 0o600)
        changed = []
        try:
            for name, content in payload.items():
                if original[name] == content:
                    continue
                # Same-directory rename publishes each fully written file.
                changed.append(name)
                atomic_write(TARGET / name, content)
            for name, content in payload.items():
                if (TARGET / name).read_bytes() != content:
                    raise RuntimeError('Installed file readback failed: ' + name)
        except BaseException:
            for name in reversed(changed):
                atomic_write(TARGET / name, original[name])
            status['state'] = 'rolled-back'
            atomic_write(RECORD / 'status.json', (json.dumps(status, indent=2) + '\n').encode(), 0o600)
            raise
        status['state'] = 'complete'
        atomic_write(RECORD / 'status.json', (json.dumps(status, indent=2) + '\n').encode(), 0o600)
    print('UPDATE COMPLETE: four application files verified. Blockchain data, wallets, passwords and settings were not modified.')
    print('Please close the backup dialog and restart Bitcoin Core Node normally before testing. Do not reinstall the OS.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Update refused or rolled back: ' + str(exc), file=sys.stderr)
        sys.exit(1)
