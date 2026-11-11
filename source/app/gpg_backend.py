"""Stock GnuPG file encryption, with provisional output restricted to private RAM.

The caller supplies a session-policy-verified RAM root and publishes only after
success. This module also requires an owned 0700 tmpfs directory. Passphrases
travel through an anonymous pipe, never argv/environment/files/transcripts.
Python memory copies are not claimed to be securely erased. Linux/GnuPG 2.4
is the tested platform; new backups always use widely compatible AES256-CFB+MDC, without downgrade fallback.
"""
from __future__ import annotations
import ctypes
import hashlib
import os
from pathlib import Path
import resource
import selectors
import signal
import stat
import subprocess
import tempfile
import time

ENCRYPTION_PROFILE = 'AES256-MDC'
OPERATION_TIMEOUT = 300.0
S2K_COUNT = 65011712
_TMPFS_MAGIC = 0x01021994


class GPGError(Exception):
    """Fixed, non-secret backend failure suitable for a user-facing wrapper."""


def _check(progress, deadline):
    if progress is not None:
        progress.check()  # Preserve the caller's Cancelled exception.
    if time.monotonic() >= deadline:
        raise GPGError('GPG exceeded the operation time limit.')


def _password(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise GPGError('Use a non-empty passphrase without control characters.')
    try:
        encoded = value.encode('utf-8')
    except UnicodeError:
        raise GPGError('The passphrase is not valid UTF-8.') from None
    if len(encoded) > 512:
        raise GPGError('Use a passphrase of at most 512 UTF-8 bytes.')
    return encoded + b'\n'


def _path(value):
    path = Path(os.path.abspath(value))
    if any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
        raise GPGError('Control characters in file names are not supported.')
    for component in (path, *path.parents):
        if component.is_symlink():
            raise GPGError('Symbolic links are not supported for this operation.')
    return path


def _tmpfs(fd):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.fstatfs.argtypes = [ctypes.c_int, ctypes.c_void_p]
    libc.fstatfs.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(256)
    if libc.fstatfs(fd, buffer) or ctypes.c_long.from_buffer(buffer).value != _TMPFS_MAGIC:
        raise GPGError('GPG working files must remain in the verified RAM filesystem.')


def _private_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise GPGError('GPG requires an owned private RAM directory with mode 0700.')
        _tmpfs(fd)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _executable(value):
    path = Path(value or '/usr/bin/gpg')
    if not path.is_absolute():
        raise GPGError('An explicit trusted GnuPG executable is required.')
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.geteuid())
            or info.st_mode & 0o022 or not os.access(path, os.X_OK)):
        raise GPGError('The trusted GnuPG executable is unavailable.')
    return str(path)


def _identity(fd):
    info = os.fstat(fd)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _hash(fd, progress, deadline):
    os.lseek(fd, 0, os.SEEK_SET)
    result = hashlib.sha256()
    while True:
        _check(progress, deadline)
        data = os.read(fd, 1024*1024)
        if not data:
            break
        result.update(data)
    os.lseek(fd, 0, os.SEEK_SET)
    return result.digest()


class _Status:
    # No status arguments containing a filename/passphrase/plaintext are kept.
    _FAIL = {b'ERROR', b'FAILURE', b'BADMDC', b'ERRMDC', b'DECRYPTION_FAILED', b'NODATA',
             b'BADARMOR', b'UNEXPECTED', b'BAD_PASSPHRASE', b'MISSING_PASSPHRASE',
             b'NO_SECKEY', b'NO_PUBKEY', b'ENC_TO', b'BADSIG', b'ERRSIG'}
    _TRACK = {b'BEGIN_ENCRYPTION', b'END_ENCRYPTION', b'BEGIN_DECRYPTION',
              b'DECRYPTION_INFO', b'PLAINTEXT', b'DECRYPTION_OKAY', b'GOODMDC', b'END_DECRYPTION'}

    def __init__(self):
        self.events = []
        self.info = None
        self.encryption_info = None
        self.failed = False

    def line(self, line):
        if not line.startswith(b'[GNUPG:] '):
            raise GPGError('GPG returned an invalid status stream.')
        word, _, arguments = line[9:].partition(b' ')
        if word in self._FAIL:
            self.failed = True
        if word in self._TRACK:
            self.events.append(word)
            if len(self.events) > 16:
                raise GPGError('GPG returned an unexpected message structure.')
        if word == b'DECRYPTION_INFO':
            self.info = arguments.split()
        if word == b'BEGIN_ENCRYPTION':
            self.encryption_info = arguments.split()

    def finish(self, mode):
        if self.failed:
            raise GPGError('GPG encryption or authentication failed.')
        if mode == 'encrypt':
            if self.events != [b'BEGIN_ENCRYPTION', b'END_ENCRYPTION'] or self.encryption_info != [b'2', b'9']:
                raise GPGError('GPG did not create the required AES-256 CFB+MDC backup.')
            return ENCRYPTION_PROFILE
        expected = [b'BEGIN_DECRYPTION', b'DECRYPTION_INFO', b'PLAINTEXT',
                    b'DECRYPTION_OKAY', b'END_DECRYPTION']
        # GOODMDC is obsolete in GnuPG's protocol. Its absence is allowed only
        # with every protected-profile and completed-decryption fact intact;
        # zero/one at the observed position never overrides exit/failure checks.
        with_goodmdc = expected[:-1] + [b'GOODMDC'] + expected[-1:]
        if self.events not in (expected, with_goodmdc):
            raise GPGError('The file is not a single authenticated encrypted backup.')
        if self.info == [b'0', b'9', b'2']:
            return 'AES256-OCB'  # Read-only compatibility with older Vault backups.
        if self.info == [b'2', b'9', b'0']:
            return ENCRYPTION_PROFILE
        raise GPGError('The encrypted backup uses an unsupported protection profile.')


def _run(mode, source_fd, output_fd, secret, work, executable, progress, deadline, max_output_bytes, embedded_name):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    home = work/'home'
    home.mkdir(mode=0o700)
    env = dict(PATH='/usr/bin:/bin', LANG='C.UTF-8', LC_ALL='C.UTF-8',
               HOME=str(home), GNUPGHOME=str(home), XDG_RUNTIME_DIR=str(work),
               TMPDIR=str(work), TMP=str(work), TEMP=str(work))
    pass_read, pass_write = os.pipe2(os.O_CLOEXEC)
    status_read, status_write = os.pipe2(os.O_CLOEXEC)
    descriptors = {pass_read, pass_write, status_read, status_write}
    process = None
    try:
        os.write(pass_write, secret)  # <=513 bytes, below PIPE_BUF; no child wait.
        os.close(pass_write); descriptors.remove(pass_write)
        args = [executable, '--no-options', '--homedir', str(home), '--batch', '--no-tty',
                '--no-autostart', '--no-keyring', '--disable-dirmngr',
                '--no-auto-key-locate', '--no-auto-key-retrieve', '--pinentry-mode', 'loopback',
                '--no-symkey-cache', '--passphrase-fd', str(pass_read),
                '--status-fd', str(status_write), '--max-output', str(max_output_bytes), '--output', '-']
        if mode == 'encrypt':
            args += ['--rfc4880', '--cipher-algo', 'AES256', '--s2k-mode', '3',
                     '--s2k-digest-algo', 'SHA256', '--s2k-count', str(S2K_COUNT),
                     '--no-compress', '--set-filename', embedded_name, '--symmetric']
        else:
            args += ['--decrypt']
        process = subprocess.Popen(args, stdin=source_fd, stdout=output_fd,
                                   stderr=subprocess.DEVNULL, env=env, cwd=work,
                                   pass_fds=(pass_read, status_write), start_new_session=True)
        for fd in (pass_read, status_write):
            os.close(fd); descriptors.remove(fd)
        os.set_blocking(status_read, False)
        status = _Status(); buffer = b''; total = 0; eof = False
        with selectors.DefaultSelector() as selector:
            selector.register(status_read, selectors.EVENT_READ)
            while not eof or process.poll() is None:
                _check(progress, deadline)
                if os.fstat(output_fd).st_size > max_output_bytes:
                    raise GPGError('GPG output exceeded the private RAM limit.')
                if eof:
                    time.sleep(.02)
                    continue
                for _, _ in selector.select(.1):
                    data = os.read(status_read, 8192)
                    if not data:
                        eof = True
                        break
                    total += len(data); buffer += data
                    if total > 256*1024:
                        raise GPGError('GPG exceeded the bounded status stream.')
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        if len(line) > 4096:
                            raise GPGError('GPG returned an oversized status line.')
                        status.line(line)
                    if len(buffer) > 4096:
                        raise GPGError('GPG returned an oversized status line.')
        if buffer or process.wait() != 0:
            raise GPGError('GPG encryption or authentication failed.')
        return status.finish(mode)
    except BaseException:
        if process is not None:
            # Never signal a PID/PGID after Popen has reaped its leader. Before
            # wait/poll, even an exited leader retains its PID, so its original
            # process group can safely be stopped if a writer holds the pipe.
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
        raise
    finally:
        for fd in descriptors:
            os.close(fd)


def _transform(mode, source, destination, password, *, ram_root, progress, executable, deadline, max_output_bytes, embedded_name='', verify_roundtrip=True):
    source_fd = root_fd = parent_fd = output_fd = None
    created = False; output_identity = None
    try:
        _check(progress, deadline)
        secret = _password(password)
        root = _path(ram_root); src = _path(source); dest = _path(destination)
        root_fd = _private_directory(root)
        if not dest.is_relative_to(root) or dest == root:
            raise GPGError('GPG provisional output must be inside the private RAM directory.')
        for parent in (dest.parent, *dest.parent.parents):
            if parent == root: break
            fd = _private_directory(parent); os.close(fd)
        parent_fd = _private_directory(dest.parent)
        if os.fstat(parent_fd).st_dev != os.fstat(root_fd).st_dev:
            raise GPGError('GPG output is outside the private RAM filesystem.')
        exe = _executable(executable)
        source_fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(source_fd).st_mode):
            raise GPGError('Select one regular file for GPG encryption or recovery.')
        before = _identity(source_fd)
        expected = _hash(source_fd, progress, deadline) if mode == 'encrypt' and verify_roundtrip else None
        if _identity(source_fd) != before:
            raise GPGError('The input file changed during backup.')
        output_fd = os.open(dest.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                            0o600, dir_fd=parent_fd)
        created = True; output_identity = os.fstat(output_fd)
        with tempfile.TemporaryDirectory(prefix='.vault-gpg-', dir=root) as temporary:
            work = Path(temporary)
            profile = _run(mode, source_fd, output_fd, secret, work, exe, progress, deadline, max_output_bytes, embedded_name)
            if os.fstat(output_fd).st_size > max_output_bytes:
                raise GPGError('GPG output exceeded the private RAM limit.')
            if os.lseek(source_fd, 0, os.SEEK_CUR) != before[2] or _identity(source_fd) != before:
                raise GPGError('GPG did not consume an unchanged complete input file.')
            os.fsync(output_fd)
            if mode == 'encrypt':
                if os.fstat(output_fd).st_size == 0:
                    raise GPGError('GPG did not create an encrypted backup.')
                if verify_roundtrip:
                    # Actual decrypt/authentication and byte comparison, not extension/status only.
                    recovered = work/'readback'
                    readback_profile = _transform('decrypt', dest, recovered, password,
                        ram_root=root, progress=progress, executable=exe, deadline=deadline, max_output_bytes=max_output_bytes)
                    if readback_profile != ENCRYPTION_PROFILE:
                        raise GPGError('The new backup does not use the required AES-256 MDC protection.')
                    fd = os.open(recovered, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                    try:
                        if _hash(fd, progress, deadline) != expected:
                            raise GPGError('The encrypted backup did not recover the expected file.')
                    finally:
                        os.close(fd)
                    if _identity(source_fd) != before:
                        raise GPGError('The input file changed during backup verification.')
        _check(progress, deadline)
        created = False  # Successful provisional output belongs to the caller.
        return profile
    except OSError:
        raise GPGError('A GPG input, output or executable is unavailable or inaccessible.') from None
    finally:
        if created and parent_fd is not None:
            try:
                info = os.stat(dest.name, dir_fd=parent_fd, follow_symlinks=False)
                if (info.st_dev, info.st_ino) == (output_identity.st_dev, output_identity.st_ino):
                    os.unlink(dest.name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        for fd in (output_fd, source_fd, parent_fd, root_fd):
            if fd is not None: os.close(fd)


def encrypt_file(source, destination, password, *, ram_root, progress=None, executable=None,
                 max_output_bytes=256*1024*1024, embedded_name='', verify_roundtrip=True):
    """Create authenticated AES256-MDC; optionally declare a generic inner file type.

    Backup and Restore can explicitly skip a round-trip test with
    verify_roundtrip=False. The normal Encrypt Files path keeps it enabled.
    GPG completion, protected RAM output, full input consumption and write
    errors are always checked. Decryption authentication cannot be disabled.
    No wallet name, filesystem path, source name or secret enters the packet.
    Layered Node/Vault archives contain an inner GPG, TAR, or a single wallet.dat.
    """
    if type(verify_roundtrip) is not bool:
        raise GPGError('Invalid backup verification mode.')
    if embedded_name not in ('', 'inner.gpg', 'payload.tar', 'wallet.dat'):
        raise GPGError('Unsupported encrypted payload filename.')
    return _transform('encrypt', source, destination, password, ram_root=ram_root,
        progress=progress, executable=executable, deadline=time.monotonic()+OPERATION_TIMEOUT,
        max_output_bytes=max_output_bytes, embedded_name=embedded_name, verify_roundtrip=verify_roundtrip)


def decrypt_file(source, destination, password, *, ram_root, progress=None, executable=None, max_output_bytes=256*1024*1024):
    """Return only a fully authenticated AES256-OCB or AES256-MDC RAM file."""
    return _transform('decrypt', source, destination, password, ram_root=ram_root,
        progress=progress, executable=executable, deadline=time.monotonic()+OPERATION_TIMEOUT, max_output_bytes=max_output_bytes)
