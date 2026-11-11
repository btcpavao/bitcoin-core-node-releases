"""GPG file encryption using Vault's reviewed backend and Node's RAM policy."""
from contextlib import contextmanager
import ctypes
import errno
import os
from pathlib import Path
import resource
import shutil
import stat
import subprocess
import sys
import tempfile
import time

TITLE = 'Bitcoin Core Node — File Encryption'
class Cancelled(Exception): pass
class BackupError(Exception): pass

def harden():
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

def dialog(*args):
    r = subprocess.run(['/usr/bin/zenity', *args], stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL, encoding='utf-8')
    if r.returncode != 0: raise Cancelled()
    # Remove exactly Zenity's final line ending, not passphrase whitespace.
    return r.stdout[:-1] if r.stdout.endswith('\n') else r.stdout

def message(text, error=False, *, operation=None):
    from message_dialog import show_message
    options = {'error': error}
    if operation is not None:
        options['operation'] = operation
    show_message(text, **options)

def validate_password(password):
    if not password or len(password.encode('utf-8')) > 512:
        raise BackupError('Use a non-empty passphrase of at most 512 UTF-8 bytes.')
    if any(ord(c) < 32 or ord(c) == 127 for c in password):
        raise BackupError('Control characters and line breaks are not supported in passphrases.')

class Progress:
    def __init__(self):
        self.p = subprocess.Popen(['/usr/bin/zenity', '--progress', '--pulsate',
            '--auto-close', '--no-markup', '--width=480', '--title='+TITLE,
            '--text=Processing and verifying GPG files…'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            text=True)
    def check(self):
        if self.p.poll() is not None: raise Cancelled()
    def update(self, text):
        self.check()
        try:
            self.p.stdin.write('# ' + text.replace('\n', ' ') + '\n')
            self.p.stdin.flush()
        except BrokenPipeError:
            raise Cancelled()
    def close(self):
        if self.p.poll() is None:
            try:
                self.p.stdin.write('100\n'); self.p.stdin.flush()
                self.p.wait(timeout=3)
            except (BrokenPipeError, subprocess.TimeoutExpired): self.p.terminate()
        if self.p.stdin: self.p.stdin.close()





def selected_paths(items):
    if not items: raise BackupError('No files were selected.')
    from private_workspace import canonical_path
    paths = [canonical_path(item) for item in items]
    from gpg_backend import _path
    paths = [_path(p) for p in paths]
    if len({p.name for p in paths}) != len(paths):
        raise BackupError('Please select items with distinct top-level names.')
    from layered_backend import MAX_BYTES, MAX_ENTRIES
    total = count = 0
    for p in paths:
        count += 1
        total += p.stat().st_size if p.is_file() else 0
        if any(ord(c) < 32 or ord(c) == 127 for c in str(p)):
            raise BackupError('Control characters in file names are not supported.')
        check_regular(p)
        if p.is_dir():
            def onerror(err): raise BackupError('A selected folder cannot be read.')
            for root, dirs, files in os.walk(p, followlinks=False, onerror=onerror):
                for name in dirs + files:
                    item = Path(root)/name
                    check_regular(item)
                    count += 1
                    total += item.stat().st_size if item.is_file() else 0
                    if count > MAX_ENTRIES or total > MAX_BYTES:
                        raise BackupError('Selected data exceed the bounded RAM backup limits. Please split the backup.')
        if count > MAX_ENTRIES or total > MAX_BYTES:
            raise BackupError('Selected data exceed the bounded RAM backup limits. Please split the backup.')
    return paths

def check_regular(p):
    if any(ord(c) < 32 or ord(c) == 127 for c in str(p)):
        raise BackupError('Control characters in file names are not supported.')
    try: mode = p.lstat().st_mode
    except OSError as e: raise BackupError('A selected file is not accessible.') from e
    if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        raise BackupError('Select regular files or folders, not symbolic links or special files.')

def publish_new(src, dst):
    """Atomic, no-overwrite publication on Linux. Never remove an older backup."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is not None:
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(src), -100, os.fsencode(dst), 1) == 0: return
        code = ctypes.get_errno()
        if code not in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
            raise OSError(code, os.strerror(code))
    # Also atomic/no-overwrite, but unavailable on some removable filesystems.
    os.link(src, dst)
    os.unlink(src)





def backup_destination(destination):
    path = Path(os.path.abspath(destination))
    return path if path.suffix.lower() == '.gpg' else Path(str(path) + '.gpg')

def copy_ciphertext(source, output, progress=None):
    """Poll cancellation between encrypted blocks; never copy plaintext here."""
    deadline = time.monotonic() + 300
    while True:
        if progress:
            progress.check()
        if time.monotonic() >= deadline:
            raise BackupError('Copying the encrypted backup exceeded the operation time limit.')
        block = source.read(1024 * 1024)
        if not block:
            return
        output.write(block)

def create_backup(items, destination, passwords, *, progress=None, policy=None):
    from layered_backend import create_layers, passphrases, LayerError
    from gpg_backend import GPGError, _path
    passphrases(passwords)
    paths = selected_paths(items)
    if policy is None:
        import private_workspace as policy
    policy.check_storage()
    dest = _path(backup_destination(destination))
    if not dest.parent.is_dir() or os.path.lexists(dest):
        raise BackupError('Please choose a new backup name in an existing destination folder.')
    for source in paths:
        if source.is_dir() and dest.is_relative_to(source):
            raise BackupError('Please save the backup outside the selected folder.')
    ram_root = policy.EXPORT
    try:
        with tempfile.TemporaryDirectory(prefix='gpg-create-', dir=ram_root) as tmp:
            ciphertext = Path(tmp) / 'new.gpg'
            create_layers(paths, ciphertext, passwords, ram_root=ram_root, progress=progress)
            # Destination staging contains only fully verified ciphertext.
            with tempfile.TemporaryDirectory(prefix='.node-gpg-', dir=dest.parent) as target:
                work = Path(target) / 'new.gpg'
                with ciphertext.open('rb') as source, work.open('xb') as output:
                    copy_ciphertext(source, output, progress)
                    output.flush()
                    os.fsync(output.fileno())
                if policy.file_digest(work) != policy.file_digest(ciphertext):
                    raise BackupError('The encrypted copy failed verification. No backup was published.')
                if progress:
                    progress.check()
                try:
                    publish_new(work, dest)
                except FileExistsError:
                    raise BackupError('That backup already exists; it was left untouched.') from None
                try:
                    fd = os.open(dest.parent, os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                except OSError:
                    pass
    except (GPGError, LayerError) as exc:
        raise BackupError(str(exc)) from None
    return dest


def choose_file(title, directory):
    from password_dialog import ensure_app
    from media_file_dialog import choose_media_file
    ensure_app()
    filename = choose_media_file(None, title, str(directory))
    if not filename:
        raise Cancelled()
    return filename


def validate_for_gui(value):
    try:
        validate_password(value)
    except BackupError as exc:
        raise ValueError(str(exc)) from None


def create_ui(items):
    import private_workspace as policy
    policy.check_storage()
    if not items:
        items = [choose_file('Select a file to encrypt', policy.PRIVATE)]
    paths = selected_paths(items)
    from password_dialog import get_backup_request
    request = get_backup_request(validate_for_gui,
        policy.PRIVATE / ('encrypted-' + time.strftime('%Y%m%d-%H%M%S') + '.gpg'), items=paths)
    if request is None:
        raise Cancelled()
    destination, passwords = request
    request = None
    progress = Progress()
    try:
        result = create_backup(paths, destination, passwords, progress=progress, policy=policy)
    finally:
        passwords = None
        progress.close()
    # Like Vault: after a verified encrypted copy saved inside Private Workspace,
    # close the backup/progress UI and open the destination in Thunar. Do not
    # present a second dialog or treat an external destination as volatile.
    if result.resolve(strict=True).parent.is_relative_to(policy.PRIVATE.resolve(strict=True)):
        try:
            subprocess.Popen(['/usr/bin/thunar', str(policy.PRIVATE)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True,
                             close_fds=True)
        except OSError:
            message('Encrypted files created and verified:\n' + str(result) +
                    '\n\nOpen Files to find the archive in Private Workspace.')
        return
    message('Encrypted files created and recovery verified:\n' + str(result) +
        '\n\nOriginal files remain unchanged. Files in Private Workspace are lost at restart or shutdown. '
        'Please save the encrypted copy to USB or disk and keep its passphrases separately.')


def decrypt_files(source, destination, passwords, *, ordinary=False, progress=None, policy=None):
    from layered_backend import recover_files, LayerError
    from gpg_backend import GPGError, _path
    if policy is None:
        import private_workspace as policy
    policy.check_storage()
    source = _path(policy.canonical_path(source))
    destination = _path(policy.canonical_path(destination))
    if destination.parent != policy.PRIVATE or os.path.lexists(destination):
        raise BackupError('Please choose a new folder directly in Private Workspace.')
    with tempfile.TemporaryDirectory(prefix='gpg-decrypt-', dir=policy.EXPORT) as temporary:
        staging = Path(temporary)
        result = recover_files(source, staging/'files', passwords, ram_root=policy.EXPORT,
            workspace=staging, progress=progress, ordinary=ordinary)
        policy.share_recovered(result)
        policy.check_storage()
        if progress:
            progress.check()
        publish_new(result, destination)
    return destination


def decrypt_ui(items):
    import private_workspace as policy
    policy.check_storage()
    if not items:
        items = [choose_file('Select a GPG file to decrypt', policy.PRIVATE)]
    if len(items) != 1:
        raise BackupError('Please select one encrypted file at a time.')
    paths = selected_paths(items)
    if not paths[0].is_file():
        raise BackupError('Please select a regular encrypted file.')
    from recovery_dialog import get_recovery_request
    from layered_backend import MorePassphrases
    previous, error = [], ''
    suggested = 'decrypted-' + time.strftime('%Y%m%d-%H%M%S')
    while True:
        request = get_recovery_request(validate_for_gui, policy.PRIVATE, suggested,
            source=paths[0], previous=previous, error=error)
        previous = []
        if request is None:
            raise Cancelled()
        destination, passwords, ordinary = request
        request = None
        progress = Progress()
        try:
            result = decrypt_files(paths[0], destination, passwords, ordinary=ordinary,
                progress=progress, policy=policy)
        except MorePassphrases as exc:
            previous, error, suggested = passwords, str(exc), destination.name
            continue
        finally:
            passwords = None
            progress.close()
        break
    open_recovered_workspace(result, policy=policy)


def open_recovered_workspace(result, *, policy=None):
    """Reveal verified recovery in its RAM parent, without another success prompt.

    Called only after decryption/authentication and atomic publication succeed,
    and after the progress window closes. Never open a recovered file itself.
    A file-manager failure must not be reported as failed decryption.
    """
    if policy is None:
        import private_workspace as policy
    policy.check_storage()
    result = Path(result)
    if result.parent != policy.PRIVATE or result.is_symlink() or not result.is_dir():
        raise BackupError('The verified recovery folder is no longer available in Private Workspace.')
    try:
        process = subprocess.Popen(['/usr/bin/thunar', str(policy.PRIVATE)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        try:
            if process.wait(timeout=1) != 0:
                raise OSError('File manager did not open.')
        except subprocess.TimeoutExpired:
            pass  # A newly opened file-manager window may keep its process alive.
    except OSError:
        message('Files decrypted and authenticated:\n' + str(result) +
            '\n\nFiles could not open automatically. Please open Private Workspace from Home or Files. '
            'Your recovered files remain in RAM and are lost at restart or shutdown.',
            operation='recovery')
        return False
    return True


def main():
    harden()
    mode = sys.argv[1] if len(sys.argv) > 1 else 'decrypt'
    try:
        if os.geteuid() == 0:
            raise BackupError('Please use the Node desktop account.')
        if mode == 'create':
            create_ui(sys.argv[2:])
        elif mode == 'decrypt':
            decrypt_ui(sys.argv[2:])
        else:
            raise BackupError('Unknown file operation.')
    except Cancelled:
        return 0
    except Exception as exc:
        from private_workspace import WorkspaceError
        from gpg_backend import GPGError
        from layered_backend import LayerError
        safe = isinstance(exc, (BackupError, WorkspaceError, GPGError, LayerError))
        message(str(exc) if safe else 'The operation could not be completed. Originals and existing encrypted files remain available.',
            error=True, operation='recovery' if mode == 'decrypt' else None)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
