"""Fail-closed policy for Node's volatile file workspace; Core data stay persistent."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import resource
import stat
import subprocess

ROOT = Path('/run/core-node-private')
PRIVATE = ROOT / 'workspace'
PSBT = ROOT / 'psbt'
USER = ROOT / 'user'
EXPORT = USER / 'export'


class WorkspaceError(RuntimeError):
    pass


def has_contents():
    """Count every immediate entry, including hidden files and empty folders.

    Unavailable or unsafe storage never skips the data-loss confirmations.
    No file contents or symbolic-link targets are read.
    """
    try:
        folder = check_storage()
        for current in (folder, check_psbt_storage()):
            with os.scandir(current) as entries:
                if next(entries,None) is not None:return True
        return False
    except (WorkspaceError, OSError, KeyError):
        return True


def check_storage():
    if not Path('/etc/bitcoin-core-node/installed').is_file():
        raise WorkspaceError('Private Workspace is available after installing Node.')
    node = pwd.getpwnam('node')
    core = pwd.getpwnam('bitcoinnode')
    if os.geteuid() != node.pw_uid:
        raise WorkspaceError('Please use the Node desktop account.')
    if Path('/proc/swaps').read_text().splitlines()[1:]:
        raise WorkspaceError('Swap is active. Please restart Node before using Private Workspace.')
    try:
        rows = json.loads(subprocess.check_output(
            ['/usr/bin/findmnt', '-J', '-M', str(ROOT), '-o', 'TARGET,FSTYPE,OPTIONS'],
            text=True, stderr=subprocess.DEVNULL, timeout=10))['filesystems']
        if (len(rows) != 1 or rows[0]['target'] != str(ROOT) or rows[0]['fstype'] != 'tmpfs'
                or not {'noswap', 'nodev', 'nosuid', 'noexec'}.issubset(rows[0]['options'].split(','))):
            raise ValueError()
        root = ROOT.lstat()
        if not stat.S_ISDIR(root.st_mode) or root.st_uid != 0 or root.st_mode & 0o022:
            raise ValueError()
        for path, mode, group in [(PRIVATE, 0o2770, core.pw_gid), (USER, 0o700, node.pw_gid),
                                  (EXPORT, 0o700, node.pw_gid)]:
            info = path.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != node.pw_uid or info.st_gid != group
                    or stat.S_IMODE(info.st_mode) != mode or info.st_dev != root.st_dev):
                raise ValueError()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise WorkspaceError('Private Workspace could not be verified. Please restart Node; no disk fallback is used.') from None
    return PRIVATE


def canonical_path(value):
    """Resolve only our checked home shortcut, never arbitrary source links."""
    path = Path(os.path.abspath(value))
    link = Path('/home/node/Private Workspace')
    if path.is_relative_to(link):
        if not link.is_symlink() or link.readlink() != PRIVATE:
            raise WorkspaceError('The Private Workspace shortcut is unavailable.')
        path = PRIVATE / path.relative_to(link)
    return path


def file_digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').digest()


def private_environment():
    check_storage()
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    env = os.environ.copy()
    # Debian always provides C.UTF-8; an absent inherited locale makes GTK
    # reject Unicode progress text before the user can cancel or see an error.
    env.update(LANG='C.UTF-8', LC_ALL='C.UTF-8', LANGUAGE='en')
    for key, folder in [('TMPDIR', 'tmp'), ('TMP', 'tmp'), ('TEMP', 'tmp'),
                        ('XDG_CACHE_HOME', 'cache'), ('XDG_CONFIG_HOME', 'config'),
                        ('XDG_DATA_HOME', 'data'), ('XDG_STATE_HOME', 'state')]:
        env[key] = str(USER / folder)
    env['GNUPGHOME'] = str(USER / 'gnupg')
    return env


def share_recovered(directory):
    """Expose only authenticated new output to the same unprivileged Core account."""
    group = pwd.getpwnam('bitcoinnode').pw_gid
    for path in [directory, *directory.rglob('*')]:
        info = path.lstat()
        if info.st_uid != os.geteuid() or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise WorkspaceError('Unexpected recovered file; nothing was published.')
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise WorkspaceError('Unexpected recovered link; nothing was published.')
        os.chown(path, -1, group, follow_symlinks=False)
        path.chmod(0o750 if path.is_dir() else 0o640)


def check_psbt_storage():
    """Refuse disk fallback, unsafe links or a foreign mount for PSBT exchange."""
    check_storage()
    node=pwd.getpwnam('node');core=pwd.getpwnam('bitcoinnode')
    try:
        info=PSBT.lstat();base=ROOT.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid!=node.pw_uid or
            info.st_gid!=core.pw_gid or stat.S_IMODE(info.st_mode)!=0o2770 or
            info.st_dev!=base.st_dev):raise ValueError()
    except (OSError,ValueError):
        raise WorkspaceError('PSBT Transfer Folder is unavailable. Restart Node; no disk fallback is used.') from None
    return PSBT
