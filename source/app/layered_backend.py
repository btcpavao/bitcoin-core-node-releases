"""Standard TAR inside nested stock GnuPG messages. No proprietary container.

Only a validated, complete uncompressed TAR terminates Vault recovery. A user's
original GPG/TAR is an entry in that TAR, never another layer to unwrap. Ordinary
GPG files use an explicit single-layer recovery mode; guessing is unsafe.
All provisional files live under the caller's storage-policy-verified RAM root.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import sqlite3
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile
import time
from gpg_backend import (GPGError, encrypt_file, decrypt_file, _password, _path,
                         _private_directory, _identity)

MAX_LAYERS = 16
MAX_ENTRIES = 10000
MAX_BYTES = 256 * 1024 * 1024
TOTAL_TIMEOUT = 900.0


class LayerError(RuntimeError):
    pass


class MorePassphrases(LayerError):
    """No supplied unused secret opened the next authenticated layer."""


class Budget:
    def __init__(self, progress=None):
        self.progress = progress
        self.deadline = time.monotonic() + TOTAL_TIMEOUT

    def check(self):
        if self.progress:
            self.progress.check()
        if time.monotonic() > self.deadline:
            raise LayerError('The backup operation exceeded its time limit.')

    def update(self, text):
        self.check()
        if self.progress and hasattr(self.progress, 'update'):
            self.progress.update(text)


def passphrases(values):
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise LayerError('Please supply a list of independent passphrases.')
    if not 1 <= len(values) <= MAX_LAYERS:
        raise LayerError('Please supply between 1 and 16 passphrases.')
    for value in values:
        _password(value)
    if len(set(values)) != len(values):
        raise LayerError('Each encryption layer needs a different passphrase.')
    return list(values)


def check_ram(root):
    root = _path(root)
    fd = _private_directory(root)
    os.close(fd)
    return root


def size_limit(root):
    # Leave headroom for TAR, encrypted layers, readback and recovered files.
    free = shutil.disk_usage(root).free
    limit = min(MAX_BYTES, free // 5)
    if limit < 1024 * 1024:
        raise LayerError('Private Workspace does not have enough free RAM.')
    return limit


def digest(path, budget):
    value = hashlib.sha256()
    with open(path, 'rb') as stream:
        while block := stream.read(1024 * 1024):
            budget.check()
            value.update(block)
    return value.digest()


def member_name(name):
    if (not name or name.startswith('/') or '\\' in name or
            any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise LayerError('The archive contains an unsafe file name.')
    parts = name.rstrip('/').split('/')
    if any(p in ('', '.', '..') for p in parts) or ':' in parts[0]:
        raise LayerError('The archive contains an unsafe path.')
    return PurePosixPath(*parts)


def open_source(path):
    """Pin every ancestor directory before opening a selected source."""
    path = _path(path)
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for name in path.parts[1:-1]:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            os.close(parent)
            parent = child
        return os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    finally:
        os.close(parent)


class CheckedReader:
    def __init__(self, stream, budget):
        self.stream, self.budget = stream, budget

    def read(self, count):
        self.budget.check()
        return self.stream.read(min(count, 1024 * 1024))


def package(items, destination, *, limit, budget):
    """Stable regular files/directories only; no symlinks, devices or sidecars."""
    paths = sorted((_path(p) for p in items), key=lambda p: str(p))
    if not paths or len({p.name for p in paths}) != len(paths):
        raise LayerError('Please select items with distinct top-level names.')
    for p in paths:
        if any(p != q and p.is_relative_to(q) for q in paths):
            raise LayerError('Please do not select both a folder and an item inside it.')
        if destination.is_relative_to(p):
            raise LayerError('Please select inputs outside the private staging directory.')
    count = total = 0
    with destination.open('xb') as output, tarfile.open(fileobj=output, mode='w', format=tarfile.PAX_FORMAT) as tar:
        def add(path, name, parent_fd=None):
            nonlocal count, total
            budget.check()
            member_name(name)
            if parent_fd is None:
                fd = open_source(path)
            else:
                fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent_fd)
            try:
                before = _identity(fd)
                meta = os.fstat(fd)
                count += 1
                if count > MAX_ENTRIES:
                    raise LayerError('Too many selected files; please split this backup.')
                entry = tarfile.TarInfo(name)
                entry.uid = entry.gid = entry.mtime = 0
                entry.uname = entry.gname = ''
                if stat.S_ISDIR(meta.st_mode):
                    entry.type = tarfile.DIRTYPE
                    entry.mode = 0o700
                    tar.addfile(entry)
                    names = sorted(os.listdir(fd))
                    # Keep path and opened directory identity consistent before descent.
                    for child in names:
                        current = os.stat(path, follow_symlinks=False)
                        if (current.st_dev, current.st_ino) != before[:2]:
                            raise LayerError('A selected directory changed during backup.')
                        add(path / child, name + '/' + child, fd)
                elif stat.S_ISREG(meta.st_mode):
                    total += meta.st_size
                    if total + count * 2048 + 10240 > limit:
                        raise LayerError('Selected data exceed the available RAM backup limit.')
                    entry.size = meta.st_size
                    entry.mode = 0o600
                    with os.fdopen(os.dup(fd), 'rb') as stream:
                        tar.addfile(entry, CheckedReader(stream, budget))
                else:
                    raise LayerError('Symbolic links and special files cannot be backed up.')
                if _identity(fd) != before:
                    raise LayerError('A selected file or directory changed during backup.')
                if output.tell() > limit:
                    raise LayerError('The TAR package exceeds the RAM limit.')
            finally:
                os.close(fd)
        for path in paths:
            add(path, path.name)
    if destination.stat().st_size > limit:
        raise LayerError('The TAR package exceeds the RAM limit.')


def inspect_tar(path, *, limit, budget):
    """Validate all entries and complete end padding before extracting anything."""
    length = path.stat().st_size
    if length < 1024 or length > limit or length % 512:
        raise LayerError('The recovered payload is not a complete supported TAR archive.')
    entries, names, total, end = [], {}, 0, 0
    try:
        with tarfile.open(path, mode='r:', errorlevel=2) as tar:
            for member in tar:
                budget.check()
                name = member_name(member.name)
                if len(entries) >= MAX_ENTRIES or name in names:
                    raise LayerError('The archive has duplicate entries or too many files.')
                if not (member.isreg() or member.isdir()) or member.sparse is not None:
                    raise LayerError('Archive links, special files and sparse files are not supported.')
                if member.size < 0 or (member.isdir() and member.size):
                    raise LayerError('The archive has invalid entry sizes.')
                total += member.size
                if total > limit:
                    raise LayerError('The recovered archive exceeds the RAM limit.')
                for parent in name.parents:
                    if parent in names and not names[parent]:
                        raise LayerError('The archive contains conflicting file paths.')
                if member.isreg() and any(name in other.parents for other in names):
                    raise LayerError('The archive contains conflicting file paths.')
                end = member.offset_data + ((member.size + 511) // 512) * 512
                if end > length - 1024:
                    raise LayerError('The archive is truncated.')
                names[name] = member.isdir()
                entries.append(member)
        if not entries:
            raise LayerError('An empty or unrecognized archive cannot be recovered.')
        with path.open('rb') as stream:
            stream.seek(end)
            if len(stream.read(1024)) != 1024:
                raise LayerError('The archive has no complete end marker.')
            stream.seek(end)
            while block := stream.read(1024 * 1024):
                budget.check()
                if any(block):
                    raise LayerError('The archive has unexpected trailing data.')
    except (tarfile.TarError, UnicodeError, ValueError, OverflowError):
        raise LayerError('The recovered TAR archive is malformed.') from None
    return entries


def is_tar_payload(path):
    # A standard TAR checksum/magic, never its filename, selects validation.
    with path.open('rb') as stream:
        block = stream.read(512)
    if len(block) != 512:
        return False
    try:
        tarfile.TarInfo.frombuf(block, 'utf-8', 'strict')
        return True
    except (tarfile.TarError, UnicodeError, ValueError):
        return False


def is_direct_wallet(path):
    """Only a valid Bitcoin Core SQLite wallet.dat may bypass TAR.

    Inspect authenticated bytes, never the decrypted filename or extension.
    Only the existing Core-supported single-table wallet schema is accepted.
    """
    try:
        if not path.is_file() or path.stat().st_size < 100:
            return False
        with path.open('rb') as f:
            if f.read(16) != b'SQLite format 3\x00':
                return False
        # Read-only URI and query_only avoid modifying the decrypted snapshot.
        connection = sqlite3.connect(path.resolve(strict=True).as_uri()+'?mode=ro',
                                     uri=True, timeout=5)
        try:
            connection.execute('PRAGMA query_only=ON')
            if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                return False
            if connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall() != [('main',)]:
                return False
            # Structural check; full record hashing is done by export.wallet_digest.
            connection.execute('SELECT key, value FROM main LIMIT 1').fetchall()
            return True
        finally:
            connection.close()
    except (OSError, RuntimeError, sqlite3.Error, ValueError):
        return False


def stage_direct_wallet(source, destination, *, limit, budget):
    """Copy a stable verified wallet snapshot into private RAM; never alter input."""
    fd = open_source(source)
    try:
        before = _identity(fd)
        if not stat.S_ISREG(os.fstat(fd).st_mode) or before[2] > limit:
            raise LayerError('Wallet exceeds the available RAM backup limit.')
        with destination.open('xb') as output:
            while True:
                budget.check()
                data=os.read(fd, 1024*1024)
                if not data: break
                output.write(data)
        if _identity(fd) != before or destination.stat().st_size != before[2]:
            raise LayerError('Wallet changed during RAM snapshot staging.')
        if not is_direct_wallet(destination):
            raise LayerError('A selected wallet.dat is not a complete supported Bitcoin Core SQLite wallet.')
    finally:
        os.close(fd)


def unpack(path, destination, *, limit, budget):
    entries = inspect_tar(path, limit=limit, budget=budget)
    destination.mkdir(mode=0o700)  # Exclusive new directory; caller cleans failure.
    with tarfile.open(path, 'r:') as tar:
        for member in entries:
            budget.check()
            target = destination.joinpath(*member_name(member.name).parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if member.isdir():
                target.mkdir(mode=0o700, exist_ok=True)
                continue
            source = tar.extractfile(member)
            if source is None:
                raise LayerError('An archive file could not be read.')
            with source, target.open('xb') as output:
                remaining = member.size
                while remaining:
                    budget.check()
                    block = source.read(min(remaining, 1024 * 1024))
                    if not block:
                        raise LayerError('An archive file is truncated.')
                    output.write(block)
                    remaining -= len(block)
    return destination


@contextmanager
def recover_payload(source, secrets, *, ram_root, progress=None, ordinary=False):
    """Yield a fully authenticated TAR, or one explicit ordinary GPG payload.

    On failure, including a missing secret, all partial results are removed.
    A retry starts from the original ciphertext and may supply more passphrases.
    No layer count is inferred from packet or filename metadata.
    """
    remaining = passphrases(secrets)
    root = check_ram(ram_root)
    limit = size_limit(root)
    budget = progress if isinstance(progress, Budget) else Budget(progress)
    with tempfile.TemporaryDirectory(prefix='layers-recover-', dir=root) as temporary:
        current = _path(source)
        for number in range(1, MAX_LAYERS + 1):
            budget.update('Authenticating encryption layer ' + str(number) + '…')
            recovered = Path(temporary) / ('layer-' + str(number))
            used = None
            for index, secret in enumerate(remaining):
                budget.check()
                try:
                    profile = decrypt_file(current, recovered, secret, ram_root=root, progress=budget,
                                           max_output_bytes=limit)
                    if not ordinary and profile not in ('AES256-MDC', 'AES256-OCB'):
                        recovered.unlink()
                        raise GPGError('Node/Vault layers require AES-256 with verified MDC or legacy OCB authentication.')
                except GPGError:
                    continue
                used = index
                break
            if used is None:
                raise MorePassphrases('No available passphrase opened the next layer. Please add a missing passphrase or correct an entry. A damaged or unsupported file can also cause this failure.')
            remaining.pop(used)
            if number > 1:
                current.unlink()
            current = recovered
            if ordinary:
                yield current
                return
            if is_tar_payload(current):
                inspect_tar(current, limit=limit, budget=budget)
                yield current
                return
            if is_direct_wallet(current):
                yield current
                return
            if not remaining:
                raise MorePassphrases('Another encryption layer may remain. Please add its passphrase. For an ordinary GPG file, please select single-layer recovery explicitly.')
        raise LayerError('The supported limit of 16 encryption layers was exceeded.')


def create_layers(items, destination, secrets, *, ram_root, progress=None):
    secrets = passphrases(secrets)
    root = check_ram(ram_root)
    destination = _path(destination)
    if not destination.is_relative_to(root) or os.path.lexists(destination):
        raise LayerError('Encrypted staging output must be new and inside verified RAM.')
    budget = Budget(progress)
    limit = size_limit(root)
    with tempfile.TemporaryDirectory(prefix='layers-create-', dir=root) as temporary:
        work = Path(temporary)
        items = list(items)
        direct = (len(items) == 1 and items[0].name == 'wallet.dat'
                  and items[0].is_file() and is_direct_wallet(items[0]))
        if direct:
            current = work / 'wallet.dat'
            budget.update('Preparing a verified single-wallet backup in RAM…')
            stage_direct_wallet(items[0], current, limit=limit, budget=budget)
        else:
            current = work / 'payload.tar'
            budget.update('Packaging selected files in private RAM…')
            package(items, current, limit=limit, budget=budget)
            inspect_tar(current, limit=limit, budget=budget)
        expected = digest(current, budget)
        for number, secret in enumerate(secrets, 1):
            budget.update('Encrypting and verifying layer ' + str(number) + ' of ' + str(len(secrets)) + '…')
            encrypted = work / ('layer-' + str(number) + '.gpg')
            # Fixed, harmless OpenPGP literal names let desktop GPG tools save
            # the first decrypted output as a recognizable .gpg, then a .tar.
            # No wallet name, original path, or passphrase is embedded.
            embedded_name = ('wallet.dat' if direct else 'payload.tar') if number == 1 else 'inner.gpg'
            encrypt_file(current, encrypted, secret, ram_root=root, progress=budget,
                         max_output_bytes=limit + 1024 * 1024,
                         embedded_name=embedded_name)
            current.unlink()
            current = encrypted
        budget.update('Verifying the complete backup recovery…')
        with recover_payload(current, list(reversed(secrets)), ram_root=root, progress=budget) as payload:
            if digest(payload, budget) != expected:
                raise LayerError('The full backup recovery did not match the original package.')
        os.link(current, destination)  # Exclusive publication inside the same RAM filesystem.
    return destination


def recover_files(source, destination, secrets, *, ram_root, workspace, progress=None, ordinary=False):
    root = check_ram(ram_root)
    workspace = check_ram(workspace)
    destination = _path(destination)
    if destination.parent != workspace or os.path.lexists(destination):
        raise LayerError('Please choose a new recovery folder directly in Private Workspace.')
    if root.stat().st_dev != workspace.stat().st_dev:
        raise LayerError('Recovery must remain on the verified private RAM filesystem.')
    budget = Budget(progress)
    with tempfile.TemporaryDirectory(prefix='.recover-', dir=workspace) as temporary:
        result = Path(temporary) / 'files'
        with recover_payload(source, secrets, ram_root=root, progress=budget, ordinary=ordinary) as payload:
            if ordinary:
                result.mkdir(mode=0o700)
                shutil.copyfile(payload, result / 'recovered-file')
            elif is_direct_wallet(payload):
                result.mkdir(mode=0o700)
                shutil.copyfile(payload, result / 'wallet.dat')
                (result / 'wallet.dat').chmod(0o600)
            else:
                unpack(payload, result, limit=size_limit(root), budget=budget)
        budget.check()
        from file_crypto import publish_new
        publish_new(result, destination)
    return destination
