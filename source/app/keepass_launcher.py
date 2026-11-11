"""Vault KeePassXC defaults, confined to Node's verified volatile profile."""
import os
from pathlib import Path
import stat
import subprocess
from private_workspace import PRIVATE, USER, WorkspaceError, private_environment

DEFAULTS = '''[General]
ConfigVersion=2
UpdateCheckMessageShown=true
RememberLastDatabases=false
RememberLastKeyFiles=false

[GUI]
CheckForUpdates=false

[PasswordGenerator]
Type=1
WordCount=6
WordList=eff_large.wordlist

[Security]
ClearClipboard=false
ClearClipboardTimeout=10
LockDatabaseIdle=true
LockDatabaseIdleSeconds=120
'''


def environment():
    env = private_environment()
    device = USER.stat().st_dev
    for name in ('config', 'data', 'state', 'cache', 'tmp'):
        info = (USER / name).lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700 or info.st_dev != device):
            raise WorkspaceError('KeePassXC requires its private RAM profile. Please restart Node.')
    directory = USER / 'config/keepassxc'
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700 or info.st_dev != device):
        raise WorkspaceError('The KeePassXC RAM profile is unavailable. Please restart Node.')
    config = directory / 'keepassxc.ini'
    try:
        fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        info = config.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_dev != device):
            raise WorkspaceError('The KeePassXC RAM configuration is unsafe. Please restart Node.')
    else:
        with os.fdopen(fd, 'w') as stream:
            stream.write(DEFAULTS)
    from file_dialog_policy import apply as prepare_dialogs
    try:prepare_dialogs(core=False)
    except (OSError,RuntimeError):pass  # The desktop watcher retries without blocking KeePassXC.
    env['QT_LINUX_ACCESSIBILITY_ALWAYS_ON'] = '1'
    return env


def launch():
    env = environment()
    return subprocess.Popen(['/usr/local/bin/core-node-keepassxc'], env=env, cwd=PRIVATE)


def main():
    import sys
    env = environment()
    if len(sys.argv) == 1:
        log = USER / 'state/keepass-generator.log'
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            subprocess.Popen(['/usr/local/bin/core-node-open-passphrase', '--pid', str(os.getpid())],
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, env=env)
    os.chdir(PRIVATE)
    release = Path('/opt/keepassxc/current').resolve(strict=True)
    binary = release / 'usr/bin/keepassxc'
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise WorkspaceError('The verified KeePassXC release is unavailable. Please check Software Updates.')
    # Run the verified bundled program directly. Its AppRun integration script
    # creates desktop shortcuts and a user systemd scope, which are unnecessary
    # in this managed desktop. Keep Qt plugins and libraries from one release.
    env.update(APPDIR=str(release), LD_LIBRARY_PATH=str(release / 'usr/lib'),
               QT_PLUGIN_PATH=str(release / 'usr/plugins'),
               QT_QPA_PLATFORM_PLUGIN_PATH=str(release / 'usr/plugins/platforms'),
               QT_QPA_PLATFORM='xcb')
    os.execve(binary, [str(binary), *sys.argv[1:]], env)
