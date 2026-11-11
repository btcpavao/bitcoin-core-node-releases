"""Shared Qt/GTK file-picker preferences, without patching upstream programs.

Desktop and Core run this as their OWN fixed accounts. No elevated writes to
user preferences, no file contents read, and no privileged mount operations.
The pinned Qt build's persistent FileDialog keys cover its native widget chooser.
"""
import os
from pathlib import Path
import pwd
import signal
import stat
import time
from PySide6.QtCore import QSettings, QUrl

MIN_WIDTH = 320
PRIVATE_CONFIG = Path('/run/core-node-private/user/config')
MEDIA_ROOT = Path('/run/core-node-media')
GTK_CSS = '/* Node file chooser: readable Places and volume labels. */\nplacessidebar { min-width: 300px; }\n'


def directory(path):
    path = Path(path)
    for parent in [*reversed(path.parents), path]:
        if parent.is_symlink():
            raise RuntimeError('A dialog preference directory is a symbolic link.')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise RuntimeError('Unsafe dialog preference directory.')
    return path


def regular_owned(path):
    if not os.path.lexists(path):
        return
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o022 or info.st_size > 1024*1024:
        raise RuntimeError('Unsafe dialog preference file.')


def qt_preferences(config, places):
    """Merge only owned chooser keys. Do not restore arbitrary binary state."""
    config = directory(config)
    target = config/'QtProject.conf'
    regular_owned(target)
    settings = QSettings(str(target), QSettings.IniFormat)
    settings.sync()
    settings.beginGroup('FileDialog')
    previous = settings.value('shortcuts', [])
    if isinstance(previous, str):
        previous = [previous]
    if not isinstance(previous, list):
        previous = []
    managed = [QUrl.fromLocalFile(str(p)).toString() for p in places]
    # Old volume bookmarks must not become misleading disconnected directories.
    others = []
    for value in previous[:64]:
        if not isinstance(value, str) or len(value) > 4096:
            continue
        url = QUrl(value)
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if any(path == prefix or path.startswith(prefix+'/') for prefix in
               ('/media/node', '/run/media/node', str(MEDIA_ROOT), '/run/core-node-private/workspace', '/run/core-node-private/psbt', '/var/lib/bitcoin-core-node/gui/USB Media (read-only)')):
            continue
        if value not in managed:
            others.append(value)
    wanted = list(dict.fromkeys([*managed, *others]))[:64]
    try:
        width = int(settings.value('sidebarWidth', 0))
    except (TypeError, ValueError):
        width = 0
    if previous != wanted:
        settings.setValue('shortcuts', wanted)
    desired_width = max(MIN_WIDTH, min(420, 35 + max((len(p.name) for p in places), default=0)*8))
    if width < desired_width:
        settings.setValue('sidebarWidth', desired_width)
    settings.endGroup()
    settings.sync()
    if settings.status() != QSettings.NoError:
        raise RuntimeError('Could not save file dialog preferences.')
    return wanted


def gtk_preferences(config, places):
    """GTK has live GIO volumes. Add RAM places and a CSS minimum width."""
    config = directory(config)
    for toolkit in ('gtk-3.0', 'gtk-4.0'):
        folder = directory(config/toolkit)
        policy = folder/'core-node-chooser.css'
        regular_owned(policy)
        if not policy.exists() or policy.read_text() != GTK_CSS:
            policy.write_text(GTK_CSS); policy.chmod(0o600)
        stylesheet = folder/'gtk.css'
        regular_owned(stylesheet)
        content = stylesheet.read_text() if stylesheet.exists() else ''
        marker = '@import url("core-node-chooser.css");'
        if marker not in content:
            stylesheet.write_text(marker+'\n'+content); stylesheet.chmod(0o600)
    # Native GTK Places already monitors mounted drives, so do not duplicate them.
    book = config/'gtk-3.0/bookmarks'
    regular_owned(book)
    text = book.read_text() if book.exists() else ''
    desired = [(p, label) for p,label in (
        (Path('/run/core-node-files/Core'), 'Core'),
        (Path('/run/core-node-private/workspace'), 'Private Workspace'),
        (Path('/run/core-node-private/psbt'), 'PSBT Transfer Folder')) if p.is_dir()]
    uris = {QUrl.fromLocalFile(str(p)).toString() for p,_ in desired}
    lines = [line for line in text.splitlines() if line.strip() and line.split()[0] not in uris]
    result = ''.join(QUrl.fromLocalFile(str(p)).toString()+' '+label+'\n' for p,label in desired)+''.join(line+'\n' for line in lines)
    if result != text:
        book.write_text(result); book.chmod(0o600)


def shortcut(home, label, target):
    link = Path(home)/label
    if link.is_symlink():
        if link.readlink() != target:
            raise RuntimeError('An existing media shortcut points elsewhere.')
    elif os.path.lexists(link):
        raise RuntimeError('An existing file conflicts with a media shortcut.')
    else:
        link.symlink_to(target)
    return link


def core_places():
    home = Path('/var/lib/bitcoin-core-node/gui')
    places = [home/'PSBT Transfer Folder', home/'Private Workspace']
    if MEDIA_ROOT.is_dir() and not MEDIA_ROOT.is_symlink():
        places += sorted((p for p in MEDIA_ROOT.iterdir()
                          if not p.is_symlink() and p.is_dir() and p.is_mount()), key=lambda p:p.name.casefold())[:16]
        places.append(shortcut(home, 'USB Media', MEDIA_ROOT))
    return [p for p in places if p.is_dir()]


def desktop_places():
    from usb_destinations import list_drives
    home=Path(pwd.getpwuid(os.geteuid()).pw_dir)
    places = [Path('/run/core-node-files/Core'), home/'Private Workspace', home/'PSBT Transfer Folder']
    places += [Path(d['mount']) for d in list_drives() if d.get('mount')]
    if Path('/media/node').is_dir():places.append(shortcut(home, 'USB Media', Path('/media/node')))
    places += [home]
    return [p for p in places if p.is_dir()]


def apply(core=False):
    account = pwd.getpwuid(os.geteuid())
    expected = 'bitcoinnode' if core else 'node'
    if account.pw_name != expected:
        raise RuntimeError('File-dialog policy is restricted to its local Node account.')
    if core:
        qt_preferences(Path('/var/lib/bitcoin-core-node/gui/.config'), core_places())
    else:
        places = desktop_places()
        for config in (Path(account.pw_dir)/'.config', PRIVATE_CONFIG):
            if config == PRIVATE_CONFIG and not config.is_dir():
                continue
            qt_preferences(config, places)
            gtk_preferences(config, places)


def main():
    import sys
    if sys.argv[1:] not in (['--watch-desktop'], ['--watch-core'], ['--desktop'], ['--core']):
        raise RuntimeError('Unsupported file-dialog policy operation.')
    mode = sys.argv[1]; core = mode.endswith('core'); watching = mode.startswith('--watch-')
    os.umask(0o077)
    alive = True
    def stop(*_):
        nonlocal alive
        alive = False
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    warned = False
    while alive:
        try:
            apply(core); warned = False
        except Exception as exc:
            if not warned:
                print('File-dialog bookmarks unavailable: '+type(exc).__name__, flush=True)
                warned = True
        if not watching:
            break
        time.sleep(2)


if __name__ == '__main__':
    main()
