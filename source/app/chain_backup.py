"""Offline blockchain copies. No wallet, cookie, network or login data is exported.

The authenticated admin entry serializes operations. External paths are opened
as the desktop user; all traversal uses no-follow directory descriptors. A
checksummed manifest is published only after a clean stop and read-back check.
Imports are staged, checked by an isolated Core, and journaled before activation.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import select
import shutil
import stat
import subprocess
import sys
import time
import tempfile
import uuid

from state import DATA, CONFIG, load_setup, verify_data_mount, CHAIN_IMPORT_RECEIPT, validate_chain_receipt

ROOTS = ('blocks', 'chainstate', 'chainstate_snapshot', 'indexes')
MANIFEST = 'chain-backup.json'
MAX_MANIFEST = 64 * 1024 * 1024
MAX_FILES = 200000
MAX_BYTES = 64 * 1024**4
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
SERVICE = 'bitcoin-core-node.service'
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}
JOURNAL = '.core-node-chain-transaction.json'


class ChainError(RuntimeError):
    pass


class Cancelled(ChainError):
    pass


class Events:
    def __init__(self, stream=None, emit=None):
        self.stream = stream
        self.emit = emit or self.output
        self.last = 0
        self.cancel_allowed = True

    @staticmethod
    def output(row):
        try:
            print(json.dumps(row), flush=True)
        except BrokenPipeError:
            raise Cancelled('The window closed. The operation was cancelled.') from None

    def check(self):
        if self.cancel_allowed and self.stream is not None:
            if select.select([self.stream], [], [], 0)[0]:
                # A cancellation line or a closed controlling window both cancel.
                os.read(self.stream.fileno(), 256)
                raise Cancelled('Cancelled. Existing blockchain data was kept.')

    def update(self, phase, done=0, total=0, *, force=False):
        self.check()
        now = time.monotonic()
        if force or now - self.last >= .2:
            self.last = now
            self.emit(dict(event='progress', phase=phase, done=done, total=total,
                           cancellable=self.cancel_allowed))


@contextmanager
def identity(uid):
    """Only external I/O changes identity; never elevate user path resolution."""
    if uid==os.geteuid():
        yield
        return
    if os.geteuid() != 0:
        if uid != os.geteuid():
            raise ChainError('Invalid local user.')
        yield
        return
    account = pwd.getpwuid(uid)
    groups = os.getgroups(); gid = os.getegid()
    try:
        os.setgroups(os.getgrouplist(account.pw_name, account.pw_gid))
        os.setegid(account.pw_gid); os.seteuid(uid)
        yield
    finally:
        os.seteuid(0); os.setegid(gid); os.setgroups(groups)


def safe_part(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value) and value not in ('.', '..')


def relative(value):
    if not isinstance(value, str):
        raise ChainError('Invalid backup file name.')
    parts = PurePosixPath(value).parts
    if (not parts or len(parts) > 12 or parts[0] not in ROOTS or
            str(PurePosixPath(*parts)) != value or not all(safe_part(p) for p in parts)):
        raise ChainError('The backup has an unsupported file layout.')
    return parts


@contextmanager
def directory_at(root_fd, parts, uid=None):
    fd = os.dup(root_fd)
    try:
        for part in parts:
            if not safe_part(part):
                raise ChainError('Invalid directory name.')
            with identity(uid) if uid is not None else _unchanged():
                child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd); fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _unchanged():
    yield


def approved_user_media_mount(resolved,record,uid):
    # A desktop USB mount is a verified block-backed FS of the logged-in
    # node account. Leftover empty /media/node/USB or /run/media/node/USB
    # directories MUST NOT silently fall back to the internal root disk.
    # Arbitrary /run, including Private Workspace, remains forbidden.
    user=pwd.getpwuid(uid).pw_name
    roots=(Path('/run/media')/user,Path('/media')/user)
    target=Path(str(record.get('target',''))).resolve(strict=False)
    source=str(record.get('source',''))
    fs=str(record.get('fstype','')).lower()
    return (any(root in target.parents for root in roots)
            and (target == resolved or target in resolved.parents)
            and source.startswith('/dev/') and fs not in
            ('tmpfs','ramfs','overlay','squashfs','proc','sysfs','devtmpfs'))


def external(path, uid, *, writing=False):
    if not isinstance(path, str) or not path.startswith('/') or len(path) > 4096 or '\x00' in path:
        raise ChainError('Please select a local folder.')
    with identity(uid):
        fd = os.open(path, DIR_FLAGS)
    try:
        resolved = Path(os.readlink('/proc/self/fd/' + str(fd)))
        try:
            records = json.loads(subprocess.check_output(
                ['/usr/bin/findmnt','-J','-T',str(resolved),'-o','TARGET,SOURCE,FSTYPE,OPTIONS'],
                text=True,timeout=10,env=ENV))['filesystems']
            mount=records[0]
            fs=mount['fstype']
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired,ValueError,KeyError,IndexError) as exc:
            raise ChainError('Could not verify the selected backup drive. Open Files and check that it is mounted.') from exc
        user_mount=approved_user_media_mount(resolved,mount,uid)
        # A disconnected /media/USB directory must never look like a drive.
        if resolved==Path('/media') or Path('/media') in resolved.parents or (
                resolved==Path('/run/media') or Path('/run/media') in resolved.parents):
            if not user_mount:
                raise ChainError('The USB drive is not mounted at the expected user mountpoint. '
                                 'Open Files or USB / External Drive and mount it before backing up.')
        # Never back up to volatile memory, the live medium, or Core's own
        # tree. Explicitly allow only the verified user UDisks2 mount.
        for forbidden in (Path('/run'), Path('/tmp'), Path('/dev'), Path('/proc'), Path('/sys'), DATA,
                          Path('/var/lib/bitcoin-core-node/gui'), Path('/run/core-node-files')):
            if resolved == forbidden or forbidden in resolved.parents:
                if forbidden == Path('/run') and user_mount:
                    continue
                raise ChainError('Choose a persistent folder or USB drive outside Core data and Private Workspace.')
        if fs in ('tmpfs', 'ramfs', 'overlay', 'squashfs'):
            raise ChainError('Choose a persistent writable folder or USB drive.')
        if writing:
            with identity(uid):
                if os.fstatvfs(fd).f_flag & os.ST_RDONLY:
                    raise ChainError('The destination is read-only.')
        return fd, resolved, fs
    except BaseException:
        os.close(fd); raise


def regular_at(fd, name, uid=None):
    with identity(uid) if uid is not None else _unchanged():
        result = os.open(name, FILE_FLAGS, dir_fd=fd)
    info = os.fstat(result)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(result)
        raise ChainError('Links and special files are not supported in blockchain backups.')
    return result


def inventory(root_fd, uid=None):
    dirs, files = [], []
    def walk(fd, path, device):
        with identity(uid) if uid is not None else _unchanged():
            names = sorted(os.listdir(fd))
        for name in names:
            relative('/'.join(path + (name,)))
            with identity(uid) if uid is not None else _unchanged():
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if info.st_dev != device:
                raise ChainError('Nested mounts are not supported in blockchain backups.')
            rel = '/'.join(path + (name,))
            if stat.S_ISDIR(info.st_mode):
                dirs.append(rel)
                with directory_at(fd, (name,), uid) as child:
                    walk(child, path + (name,), device)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                files.append(dict(path=rel, size=info.st_size))
            else:
                raise ChainError('Links and special files are not supported in blockchain backups.')
            if len(dirs) + len(files) > MAX_FILES:
                raise ChainError('The blockchain backup contains too many files.')
    for name in ROOTS:
        with identity(uid) if uid is not None else _unchanged():
            try: info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                if name in ('blocks', 'chainstate'):
                    raise ChainError('No complete local blockchain was found. Start Bitcoin Core first.') from None
                continue
        if not stat.S_ISDIR(info.st_mode):
            raise ChainError('Blockchain folders must be ordinary directories.')
        dirs.append(name)
        with directory_at(root_fd, (name,), uid) as child:
            walk(child, (name,), os.fstat(child).st_dev)
    total = sum(f['size'] for f in files)
    if not 0 < total <= MAX_BYTES:
        raise ChainError('The blockchain copy is empty or exceeds the supported size.')
    if 'blocks/index' not in dirs or not any(f['path'].startswith('blocks/blk') for f in files):
        raise ChainError('Block files or the block index are missing.')
    if not any(f['path'].startswith('chainstate/') for f in files):
        raise ChainError('The chainstate database is missing.')
    return dirs, files, total


def parse_manifest(raw, network, core_version):
    try:
        m = json.loads(raw)
        if (set(m) != {'format', 'version', 'core_version', 'network', 'height', 'bestblockhash',
                       'prune_mib', 'created_utc', 'directories', 'files', 'total_bytes'} or
                m['format'] != 'bitcoin-core-node-chain' or type(m['version']) is not int or m['version'] not in (1, 2)):
            raise ValueError()
        if m['network'] != network:
            raise ChainError('This backup is for a different Bitcoin network.')
        # Database compatibility is deliberately exact for the first format.
        if m['core_version'] != core_version:
            raise ChainError('Import this backup with the same Bitcoin Core version used to create it.')
        unknown_tip = m['version'] == 2 and m['height'] is None and m['bestblockhash'] is None
        if not unknown_tip and (type(m['height']) is not int or not 0 <= m['height'] < 2**32
                                or not isinstance(m['bestblockhash'], str)
                                or not re.fullmatch('[0-9a-f]{64}', m['bestblockhash'])):
            raise ValueError()
        if not isinstance(m['created_utc'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', m['created_utc']):
            raise ValueError()
        if type(m['prune_mib']) is not int or (m['prune_mib'] != 0 and not 550 <= m['prune_mib'] < 2**31):
            raise ValueError()
        if not isinstance(m['directories'], list) or not isinstance(m['files'], list):
            raise ValueError()
        if len(m['directories']) + len(m['files']) > MAX_FILES:
            raise ValueError()
        dirs = set()
        for d in m['directories']:
            relative(d)
            if d in dirs: raise ValueError()
            dirs.add(d)
        names = set(dirs); total = 0
        for f in m['files']:
            if set(f) != {'path', 'size', 'sha256'} or type(f['size']) is not int or not 0 <= f['size'] <= MAX_BYTES:
                raise ValueError()
            parts = relative(f['path'])
            if f['path'] in names or '/'.join(parts[:-1]) not in dirs or not re.fullmatch('[0-9a-f]{64}', f['sha256']):
                raise ValueError()
            names.add(f['path']); total += f['size']
        for d in dirs:
            parts = relative(d)
            if len(parts) > 1 and '/'.join(parts[:-1]) not in dirs: raise ValueError()
        if not {'blocks', 'blocks/index', 'chainstate'} <= dirs or type(m['total_bytes']) is not int or total != m['total_bytes'] or not 0 < total <= MAX_BYTES:
            raise ValueError()
        return m
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ChainError('This is not a complete Node chain backup. Select the folder created by Backup Chain State.') from None


def load_manifest(fd, uid, network, version):
    f = regular_at(fd, MANIFEST, uid)
    with os.fdopen(f, 'rb') as stream:
        raw = stream.read(MAX_MANIFEST + 1)
    if len(raw) > MAX_MANIFEST:
        raise ChainError('The backup manifest is too large.')
    m = parse_manifest(raw, network, version)
    dirs, files, total = inventory(fd, uid)
    if set(dirs) != set(m['directories']) or {f['path']:f['size'] for f in files} != {f['path']:f['size'] for f in m['files']}:
        raise ChainError('The backup is incomplete or changed after it was created.')
    return m


def make_dirs(fd, dirs, uid=None, owner=None):
    for d in sorted(dirs, key=lambda n: (n.count('/'), n)):
        parts = relative(d)
        with directory_at(fd, parts[:-1], uid) as parent:
            with identity(uid) if uid is not None else _unchanged():
                os.mkdir(parts[-1], 0o700, dir_fd=parent)
                child = os.open(parts[-1], DIR_FLAGS, dir_fd=parent)
            try:
                if owner is not None: os.fchown(child, *owner)
                os.fsync(child); os.fsync(parent)
            finally: os.close(child)


def copy_files(src, dst, files, events, *, src_uid=None, dst_uid=None, owner=None):
    total = sum(f['size'] for f in files); done = 0
    for entry in files:
        events.check(); parts = relative(entry['path'])
        with directory_at(src, parts[:-1], src_uid) as s, directory_at(dst, parts[:-1], dst_uid) as d:
            incoming = regular_at(s, parts[-1], src_uid)
            try:
                before = os.fstat(incoming)
                if before.st_size != entry['size']: raise ChainError('A source file changed during copying.')
                with identity(dst_uid) if dst_uid is not None else _unchanged():
                    outgoing = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=d)
                with os.fdopen(outgoing, 'wb') as target:
                    if owner is not None: os.fchown(target.fileno(), *owner)
                    digest = hashlib.sha256(); remaining = entry['size']
                    while remaining:
                        events.check()
                        block = os.read(incoming, min(4 * 1024 * 1024, remaining))
                        if not block: raise ChainError('A source file is incomplete.')
                        target.write(block); digest.update(block)
                        remaining -= len(block); done += len(block)
                        events.update('Copying blockchain data', done, total)
                    if os.read(incoming, 1): raise ChainError('A source file grew during copying.')
                    after = os.fstat(incoming)
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        raise ChainError('A source file changed during copying.')
                    actual = digest.hexdigest()
                    if entry.get('sha256', actual) != actual:
                        raise ChainError('A backup checksum did not match. Existing blockchain data was kept.')
                    entry['sha256'] = actual
                    target.flush(); os.fsync(target.fileno())
                os.fsync(d)
            finally: os.close(incoming)
    verify_files(dst, files, events, uid=dst_uid)


def verify_files(fd, files, events, uid=None):
    total = sum(f['size'] for f in files); done = 0
    for entry in files:
        parts = relative(entry['path'])
        with directory_at(fd, parts[:-1], uid) as d:
            f = regular_at(d, parts[-1], uid)
        with os.fdopen(f, 'rb') as stream:
            digest = hashlib.sha256(); count = 0
            while block := stream.read(4 * 1024 * 1024):
                events.check(); digest.update(block); count += len(block); done += len(block)
                events.update('Verifying copied files', done, total)
            if count != entry['size'] or digest.hexdigest() != entry['sha256']:
                raise ChainError('The saved copy failed verification. Please check the destination drive.')


def json_at(fd, name, obj, uid=None, owner=None):
    raw = (json.dumps(obj, sort_keys=True, indent=2) + '\n').encode()
    with identity(uid) if uid is not None else _unchanged():
        f = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    with os.fdopen(f, 'wb') as stream:
        if owner: os.fchown(stream.fileno(), *owner)
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    os.fsync(fd)


def atomic_json(path, obj, mode=0o600):
    name = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    with name.open('x') as stream:
        os.fchmod(stream.fileno(), mode)
        json.dump(obj, stream); stream.flush(); os.fsync(stream.fileno())
    os.replace(name, path)
    sync_dir(path.parent)


def sync_dir(path):
    fd = os.open(path, DIR_FLAGS)
    try: os.fsync(fd)
    finally: os.close(fd)


def command(args, timeout=330):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout, env=ENV)


def service_running():
    return subprocess.run(['/usr/bin/systemctl', 'is-active', '--quiet', SERVICE], env=ENV).returncode == 0


def stop_core():
    command(['/usr/bin/systemctl', 'stop', SERVICE])
    result = command(['/usr/bin/systemctl', 'show', '--property=Result', '--value', SERVICE], 15).stdout.strip()
    if service_running() or result != 'success':
        raise ChainError('Bitcoin Core did not stop cleanly. No blockchain copy or replacement was performed.')


@contextmanager
def core_lock(root):
    # Core uses fcntl locks on Unix. Do not remove or replace its lock inode.
    fd = os.open(root / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1: raise ChainError('Unsafe Core lock file.')
        if os.geteuid()==0:
            account=pwd.getpwnam('bitcoinnode')
            os.fchown(fd,account.pw_uid,account.pw_gid)
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError:
        raise ChainError('Bitcoin Core is still using these files. Close it before copying.') from None
    finally: os.close(fd)


def probe(root, network, events):
    """Validate only a staged import; keep bounded, actionable diagnostics."""
    events.update('Opening the copied databases with Bitcoin Core (offline)', force=True)
    with tempfile.TemporaryFile(mode='w+b') as diagnostic:
        process = subprocess.Popen(['/usr/bin/unshare', '--net', '--', '/usr/bin/python3',
                                    '/usr/lib/bitcoin-core-node/chain_probe.py', str(root), network],
                                   stdout=subprocess.PIPE, stderr=diagnostic, text=True, env=ENV)
        try:
            deadline = time.monotonic() + 900
            while process.poll() is None:
                events.check()
                if time.monotonic() > deadline:
                    raise ChainError('Opening the copied databases took too long. Existing data was kept.')
                time.sleep(.1)
            raw = process.stdout.read(8193)
            if process.returncode or len(raw) > 8192:
                diagnostic.seek(0, os.SEEK_END)
                diagnostic.seek(max(0, diagnostic.tell() - 2000))
                reason = diagnostic.read(2000).decode('utf-8', 'replace')
                reason = ' '.join(reason.split())[:1000]
                raise ChainError('Bitcoin Core could not validate the imported blockchain. Existing data was kept.'
                                 + (' Reason: ' + reason if reason else ' The validation process exited without a diagnostic.'))
            result = json.loads(raw)
            if (result['chain'] != network or type(result['blocks']) is not int or result['blocks'] < 0
                    or not re.fullmatch('[a-f0-9]{64}', result['bestblockhash'])):
                raise ChainError('Bitcoin Core returned an invalid validation result. Existing data was kept.')
            return result
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=150)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
            process.stdout.close()


def read_tip_hint(network):
    """Optional UI metadata, not an assertion about the tip after shutdown."""
    from rpc import CoreRPC, CoreError
    try:
        info = CoreRPC(timeout=5)('getblockchaininfo')
    except CoreError:
        return None
    if info.get('chain') != network:
        raise ChainError('Running Bitcoin Core uses a different network. No files were copied.')
    if (type(info.get('blocks')) is not int or not 0 <= info['blocks'] < 2**32
            or not isinstance(info.get('bestblockhash'), str)
            or not re.fullmatch('[a-f0-9]{64}', info['bestblockhash'])):
        return None
    return info


def latest_name(network):
    if network not in ('main', 'regtest', 'signet'):
        raise ChainError('Unsupported Bitcoin network.')
    return 'bitcoin-chain-' + network + '-latest.json'


def publish_latest(parent, directory, network, caller):
    """Publish a relative shortcut only after the entire snapshot is durable."""
    name = latest_name(network)
    temporary = '.chain-latest-' + uuid.uuid4().hex
    record = dict(format='bitcoin-core-node-chain-latest', version=1, directory=directory)
    try:
        json_at(parent, temporary, record, caller)
        with identity(caller):
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
    finally:
        with identity(caller):
            try: os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError: pass


def open_backup(source, caller, network, version):
    """An exact snapshot, a new drive-root shortcut, or a legacy snapshot folder."""
    fd, resolved, fs = external(source, caller)
    try:
        with identity(caller):
            try: os.stat(MANIFEST, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError: direct = False
            else: direct = True
        if direct:
            return fd, resolved, fs, load_manifest(fd, caller, network, version)
        pointer = latest_name(network)
        with identity(caller):
            try: os.stat(pointer, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError: has_pointer = False
            else: has_pointer = True
        if has_pointer:
            f = regular_at(fd, pointer, caller)
            with os.fdopen(f, 'rb') as stream:
                raw = stream.read(4097)
            try:
                record = json.loads(raw)
                name = record['directory']
                if (len(raw) > 4096 or set(record) != {'format', 'version', 'directory'}
                        or record['format'] != 'bitcoin-core-node-chain-latest'
                        or type(record['version']) is not int or record['version'] != 1
                        or not safe_part(name) or not name.startswith('bitcoin-chain-' + network + '-')):
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise ChainError('The latest-backup shortcut is invalid. Please choose the completed backup folder directly.') from None
        else:
            # Compatibility with old v1 backups; do not include incomplete copies.
            with identity(caller):
                names = [n for n in os.listdir(fd) if safe_part(n)
                         and n.startswith('bitcoin-chain-' + network + '-') and not n.endswith('.json')]
            if len(names) > 256:
                raise ChainError('There are too many snapshots here. Please select the backup folder directly.')
            candidates = []
            for n in names:
                with identity(caller): info = os.stat(n, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode): continue
                with directory_at(fd, (n,), caller) as child:
                    try: f = regular_at(child, MANIFEST, caller)
                    except FileNotFoundError: continue
                    with os.fdopen(f, 'rb') as stream: raw = stream.read(MAX_MANIFEST + 1)
                    if len(raw) > MAX_MANIFEST: raise ChainError('The backup manifest is too large.')
                    m = parse_manifest(raw, network, version)
                    candidates.append((m['created_utc'], n))
            if not candidates:
                raise ChainError('No completed blockchain backup was found on this drive. Please select the folder created by Backup Chain State.')
            name = max(candidates)[1]
        with identity(caller): child = os.open(name, DIR_FLAGS, dir_fd=fd)
        try:
            manifest = load_manifest(child, caller, network, version)
        except BaseException:
            os.close(child); raise
        os.close(fd)
        return child, resolved / name, fs, manifest
    except BaseException:
        os.close(fd); raise


def chain_root(network, data=DATA):
    if network not in ('main', 'regtest', 'signet'): raise ChainError('Unsupported Bitcoin network.')
    return data if network == 'main' else data / network


def settings_read(root):
    path = root / 'settings.json'
    if not path.exists(): return None, {}
    f = os.open(path, FILE_FLAGS)
    with os.fdopen(f, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): raise ChainError('Unsafe Bitcoin settings file.')
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024: raise ChainError('Bitcoin settings are too large.')
    settings = json.loads(raw)
    if not isinstance(settings, dict): raise ChainError('Invalid Bitcoin settings.')
    return raw, settings


def restore_settings(root, raw, owner):
    path = root / 'settings.json'
    if raw is None:
        path.unlink(missing_ok=True); sync_dir(root); return
    temporary = root / ('.chain-settings-' + uuid.uuid4().hex)
    with temporary.open('xb') as stream:
        os.fchmod(stream.fileno(), 0o600); os.fchown(stream.fileno(), *owner)
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path); sync_dir(root)


def recover(data=DATA):
    """Idempotent recovery before any Core service start, including after power loss."""
    path = data / JOURNAL
    if not path.exists(): return
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 8192:
        raise ChainError('Unsafe blockchain recovery record. Core remains stopped.')
    j = json.loads(path.read_bytes())
    if (set(j) != {'id', 'network', 'phase', 'old', 'new', 'settings_existed'} or
            not re.fullmatch('[a-f0-9]{32}', j['id']) or j['phase'] not in ('swapping', 'committed') or
            not isinstance(j['old'], list) or not isinstance(j['new'], list) or
            not set(j['old']) <= set(ROOTS) or not set(j['new']) <= set(ROOTS) or type(j['settings_existed']) is not bool):
        raise ChainError('Invalid blockchain recovery record. Core remains stopped.')
    root = chain_root(j['network'], data)
    tx = data / ('.core-node-chain-' + j['id'])
    if tx.is_symlink() or not tx.is_dir() or tx.stat().st_uid != 0:
        raise ChainError('The blockchain recovery folder is unavailable.')
    previous = tx / 'previous'; candidate = chain_root(j['network'], tx / 'candidate')
    if j['phase'] == 'swapping':
        for name in ROOTS:
            if (previous / name).exists():
                if (root / name).exists():
                    # Move the uncommitted candidate aside before restoring the old.
                    # Rename is atomic; repeated recovery can resume at any boundary.
                    if (candidate / name).exists(): raise ChainError('Ambiguous blockchain recovery state.')
                    os.rename(root / name, candidate / name); sync_dir(root); sync_dir(candidate)
                os.rename(previous / name, root / name); sync_dir(previous); sync_dir(root)
            elif name not in j['old'] and name in j['new'] and not (candidate / name).exists() and (root / name).exists():
                os.rename(root / name, candidate / name); sync_dir(root); sync_dir(candidate)
        account = pwd.getpwnam('bitcoinnode')
        raw = (tx / 'settings.previous').read_bytes() if j['settings_existed'] else None
        restore_settings(data, raw, (account.pw_uid, account.pw_gid))
    elif (tx/'receipt.json').exists():
        # Commit the first-start decision with the chain. This is idempotent
        # after power loss and leaves a previous receipt untouched on rollback.
        fd=os.open(tx/'receipt.json',FILE_FLAGS)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1 or info.st_size>4096:raise ChainError('Unsafe import receipt.')
            receipt=validate_chain_receipt(json.loads(stream.read(4097)))
        if receipt['network']!=j['network']:raise ChainError('Import receipt network mismatch.')
        atomic_json(data/CHAIN_IMPORT_RECEIPT,receipt,0o644)
    # Unlink the journal only after recovery is durable. A leftover orphan
    # transaction is harmless and cannot be selected as a normal backup.
    path.unlink(); sync_dir(data)
    shutil.rmtree(tx); sync_dir(data)


def activate(data, staging, manifest, owner, events):
    root = chain_root(manifest['network'], data)
    candidate = chain_root(manifest['network'], staging / 'candidate')
    previous = staging / 'previous'; previous.mkdir(mode=0o700)
    # The managed GUI explicitly uses DATA/settings.json for every network.
    raw, settings = settings_read(data)
    if raw is not None:
        with (staging / 'settings.previous').open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    old = []
    for name in ROOTS:
        if (root / name).is_symlink(): raise ChainError('Existing blockchain directories must not be links.')
        if (root / name).exists():
            if not (root / name).is_dir(): raise ChainError('Existing blockchain directories are unsafe.')
            old.append(name)
    new = [name for name in ROOTS if (candidate / name).exists()]
    receipt=validate_chain_receipt({key:manifest[key] for key in ('network','core_version','height','bestblockhash')}|{'version':1})
    atomic_json(staging/'receipt.json',receipt)
    j = dict(id=staging.name.removeprefix('.core-node-chain-'), network=manifest['network'],
             phase='swapping', old=old, new=new, settings_existed=raw is not None)
    sync_dir(staging)
    events.check(); events.cancel_allowed = False
    events.update('Activating verified blockchain data. Please wait', force=True)
    atomic_json(data / JOURNAL, j)
    try:
        for name in ROOTS:
            if name in old:
                os.rename(root / name, previous / name); sync_dir(root); sync_dir(previous)
            if name in new:
                os.rename(candidate / name, root / name); sync_dir(candidate); sync_dir(root)
        # Keep every other Core preference, including loaded wallet names.
        settings['prune'] = str(manifest['prune_mib'])
        restore_settings(data, (json.dumps(settings, indent=2) + '\n').encode(), owner)
        j['phase'] = 'committed'; atomic_json(data / JOURNAL, j)
    except BaseException:
        recover(data); raise
    recover(data)


def backup(destination, caller, setup, release, events, *, tip_hint=None):
    dest, resolved, fs = external(destination, caller, writing=True)
    temporary = '.chain-backup-partial-' + uuid.uuid4().hex
    output = None
    try:
        root = chain_root(setup['network'])
        # Cold-copy the fully flushed files. Never reopen the source databases
        # in a second Core process, change their pruning mode, or require the
        # full block index to fit in memory merely to copy an existing chain.
        details = tip_hint or {}
        with core_lock(root):
            src = os.open(root, DIR_FLAGS)
            try:
                dirs, files, total = inventory(src)
                if os.fstatvfs(dest).f_bavail * os.fstatvfs(dest).f_frsize < total + 128 * 1024**2:
                    raise ChainError('The selected drive does not have enough free space for this backup.')
                if fs == 'vfat' and any(f['size'] >= 2**32 for f in files):
                    raise ChainError('A file exceeds the FAT32 limit. Please use an ext4, exFAT or NTFS destination.')
                with identity(caller):
                    os.mkdir(temporary, 0o700, dir_fd=dest)
                    output = os.open(temporary, DIR_FLAGS, dir_fd=dest)
                make_dirs(output, dirs, caller)
                copy_files(src, output, files, events, dst_uid=caller)
                raw, settings = settings_read(DATA)
                try: target = int(settings.get('prune', setup['prune_mib']))
                except (ValueError, TypeError): target = setup['prune_mib']
                physically_pruned = details.get('pruneheight', 0) > 0
                if details.get('pruned') is False:
                    target = 0
                elif details.get('automatic_pruning') and type(details.get('prune_target_size')) is int:
                    target = max(550, (details['prune_target_size'] + 1024**2 - 1) // 1024**2)
                if not details and not any(f['path'] == 'blocks/blk00000.dat' for f in files):
                    physically_pruned = True
                if target not in (0, 1) and not 550 <= target < 2**31:
                    raise ChainError('The saved pruning preference is unsupported.')
                if target == 1 or physically_pruned and target == 0:
                    # Automatic 1 GiB is compatible with the native GUI and
                    # preserves the ability to resume a previously pruned chain.
                    target = 1024
                m = dict(format='bitcoin-core-node-chain', version=2, core_version=release['version'],
                         network=setup['network'], height=details.get('blocks'), bestblockhash=details.get('bestblockhash'),
                         prune_mib=target, created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                         directories=dirs, files=files, total_bytes=total)
                json_at(output, MANIFEST, m, caller)
                events.check(); events.cancel_allowed = False
                events.update('Finishing verified backup', total, total, force=True)
                name = 'bitcoin-chain-' + setup['network'] + '-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:12]
                with identity(caller):
                    os.rename(temporary, name, src_dir_fd=dest, dst_dir_fd=dest)
                    os.fsync(dest)
                publish_latest(dest, name, setup['network'], caller)
                return dict(ok=True, directory=str(resolved / name), height=details.get('blocks'),
                            tip_is_hint=True, bytes=total)
            finally: os.close(src)
    finally:
        if output is not None: os.close(output)
        with identity(caller):
            try: shutil.rmtree(temporary, dir_fd=dest)
            except FileNotFoundError: pass
        os.close(dest)


def import_backup(source, caller, setup, release, events):
    src, resolved, fs, m = open_backup(source, caller, setup['network'], release['version'])
    staging = DATA / ('.core-node-chain-' + uuid.uuid4().hex)
    try:
        if shutil.disk_usage(DATA).free < m['total_bytes'] + 512 * 1024**2:
            raise ChainError('Free enough internal disk space for the imported chain alongside the current chain. Existing files are kept until validation finishes.')
        account = pwd.getpwnam('bitcoinnode'); owner = (account.pw_uid, account.pw_gid)
        staging.mkdir(mode=0o700)
        # Core must traverse the generated transaction path as its own account.
        staging.chmod(0o711)
        candidate = staging / 'candidate'; candidate.mkdir(mode=0o700)
        os.chown(candidate, *owner)
        target = chain_root(setup['network'], candidate)
        if target != candidate:
            target.mkdir(mode=0o700); os.chown(target, *owner)
        dst = os.open(target, DIR_FLAGS)
        try:
            make_dirs(dst, m['directories'], owner=owner)
            copy_files(src, dst, m['files'], events, src_uid=caller, owner=owner)
        finally: os.close(dst)
        details = probe(candidate, setup['network'], events)
        if m['version'] == 1 and (details['blocks'] != m['height'] or details['bestblockhash'] != m['bestblockhash']):
            raise ChainError('The copied databases do not match the recorded chain tip. Existing data was kept.')
        # v2's pre-stop RPC observation is only a hint: the clean flush can
        # legitimately include additional blocks. Record the exact validated tip.
        m = dict(m, height=details['blocks'], bestblockhash=details['bestblockhash'])
        if details.get('pruneheight', 0) > 0 and m['prune_mib'] == 0:
            m['prune_mib'] = 1024
        current=chain_root(setup['network'])
        if not current.exists():
            current.mkdir(mode=0o700);os.chown(current,*owner);sync_dir(DATA)
        with core_lock(current):
            activate(DATA, staging, m, owner, events)
        return dict(ok=True, height=m['height'], bestblockhash=m['bestblockhash'],
                    directory=str(resolved), bytes=m['total_bytes'], prune_mib=m['prune_mib'])
    finally:
        os.close(src)
        if staging.exists() and not (DATA / JOURNAL).exists():
            shutil.rmtree(staging)


def perform(action, request, caller, events):
    if action not in ('chain-backup', 'chain-import') or not isinstance(request, dict) or set(request) != {'directory', 'confirmed'} or request['confirmed'] is not True:
        raise ChainError('Please review and confirm the blockchain copy operation.')
    if caller != pwd.getpwnam('node').pw_uid:
        raise ChainError('Blockchain copies are available only in the local Node desktop.')
    from upgrades import active_release
    setup = load_setup(); verify_data_mount(setup); release = active_release()
    # Validate destination/media *before* stopping Bitcoin Core. A missing
    # unplugged or unmounted USB must never interrupt blockchain validation.
    probe_fd,_,_=external(request['directory'],caller,writing=action=='chain-backup')
    os.close(probe_fd)
    if action == 'chain-import':
        check_fd, selected, _, _ = open_backup(request['directory'], caller, setup['network'], release['version'])
        os.close(check_fd)
        request = dict(request, directory=str(selected))
    running = service_running(); stopped = False; result = None; failure = None
    tip_hint = read_tip_hint(setup['network']) if running and action == 'chain-backup' else None
    lock = open(DATA / '.core-node-chain.lock', 'a')
    inhibitor = None
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inhibitor=subprocess.Popen(['/usr/bin/systemd-inhibit','--what=shutdown:sleep','--mode=block',
            '--who=Bitcoin Core Node','--why=Blockchain copy in progress','/usr/bin/cat'],
            stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=ENV)
        time.sleep(.15)
        if inhibitor.poll() is not None:raise ChainError('The system could not protect the copy from shutdown. Please try again.')
        events.update('Stopping Bitcoin Core cleanly', force=True)
        stop_core(); stopped = True
        recover()
        if action == 'chain-backup': result = backup(request['directory'], caller, setup, release, events, tip_hint=tip_hint)
        else: result = import_backup(request['directory'], caller, setup, release, events)
        result['core_was_running']=running
    except ChainError as exc:
        failure = exc
        raise
    except OSError as exc:
        failure = ChainError('Blockchain copy could not complete: ' + str(exc.strerror or type(exc).__name__)
                             + '. Please check the drive connection, permissions and free space. Existing data was kept.')
        raise failure from exc
    finally:
        lock.close()
        # The start preflight independently checks/replays a durable journal.
        if stopped and running and action == 'chain-import':
            try:
                # These are explicit, serialized maintenance restarts after a
                # verified clean stop, not a crash/restart loop. Repeated user
                # attempts must not strand Core behind systemd's start counter.
                command(['/usr/bin/systemctl', 'reset-failed', SERVICE], 15)
                command(['/usr/bin/systemctl', 'start', SERVICE])
                if result is not None: result['core_restarted'] = True
                if failure is not None:
                    failure.args = (str(failure) + ' Bitcoin Core was restarted with its original data.',)
            except Exception:
                if failure is not None:
                    failure.args = (str(failure) + ' Automatic Core restart did not complete; use the Bitcoin Core button.',)
                if result is not None:
                    result['core_restarted'] = False
                else:
                    # Keep the original failure, never report a failed copy as
                    # success just because automatic restart also failed.
                    pass
        elif result is not None: result['core_restarted'] = False
        if inhibitor is not None:
            inhibitor.stdin.close()
            try:inhibitor.wait(timeout=5)
            except subprocess.TimeoutExpired:inhibitor.terminate();inhibitor.wait(timeout=5)
    return result
