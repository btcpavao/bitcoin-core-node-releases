"""First-start Core preferences and a writable native configuration file."""
import os
from pathlib import Path
import stat
import tempfile

from state import DATA

GUI_HOME = Path('/var/lib/bitcoin-core-node/gui')
MANAGED_OPTIONS = frozenset({
    'conf','includeconf','datadir','blocksdir','walletdir','settings','wallet',
    'server','daemon','daemonwait','chain','testnet','testnet4','signet','regtest',
    'signetchallenge','signetseednode','onlynet','proxy','onion','i2psam',
    'listen','listenonion','discover','natpmp','upnp','bind','whitebind',
    'externalip','connect','addnode','seednode','dns','dnsseed','forcednsseed',
    'fixedseeds','privatebroadcast',
})


def validate_user_config(path):
    # Core merges list-valued options across configuration and CLI. Reject
    # policy overrides here rather than relying on CLI precedence for lists.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or info.st_size > 1024 * 1024):
            raise RuntimeError('Core user configuration is unsafe.')
        text = stream.read(1024 * 1024 + 1).decode('utf-8')
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line or line.startswith('['):
            continue
        name = line.split('=', 1)[0].strip().rsplit('.', 1)[-1].lower()
        if name.startswith('no'):
            name = name[2:]
        if name in MANAGED_OPTIONS or name.startswith('rpc'):
            raise RuntimeError('Please change managed network, RPC and storage options in Node Settings.')


def _create(path, content):
    """Create once without following links or replacing existing user choices."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1):
            raise RuntimeError('Core user configuration is unsafe.')
        return
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _seed_controls(path):
    """Preserve opaque upstream QVariant values byte-for-byte while adding defaults."""
    defaults=('fCoinControlFeatures','enable_psbt_controls')
    _create(path,'[General]\n'+''.join(key+'=true\n' for key in defaults))
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if info.st_size>1024*1024:
            raise RuntimeError('Core preferences exceed the safe size limit.')
        text=stream.read(1024*1024+1).decode('utf-8')
    lines=text.splitlines(keepends=True)
    general=False;end=None;found=set()
    for index,line in enumerate(lines):
        stripped=line.strip()
        if stripped.startswith('['):
            if general:end=index
            general=stripped=='[General]'
        elif general and '=' in line:
            found.add(line.split('=',1)[0].strip())
    missing=[key for key in defaults if key not in found]
    if not missing:return
    addition=''.join(key+'=true\n' for key in missing)
    if '[General]' in [line.strip() for line in lines]:
        if end is None:end=len(lines)
        if end and not lines[end-1].endswith('\n'):addition='\n'+addition
        lines.insert(end,addition)
    else:
        lines.insert(0,'[General]\n'+addition+'\n')
    fd,name=tempfile.mkstemp(prefix='.node-preferences-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            stream.write(''.join(lines));stream.flush();os.fsync(stream.fileno())
        now=path.lstat()
        if (now.st_ino,now.st_dev,now.st_mtime_ns)!=(info.st_ino,info.st_dev,info.st_mtime_ns):
            raise RuntimeError('Core preferences changed during initialization.')
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def prepare_user_files(data=DATA, home=GUI_HOME, *, network='main'):
    if network not in ('main','signet','regtest'):
        raise RuntimeError('Unsupported Core preferences network.')
    # Managed network, RPC and storage options are still explicit command-line
    # arguments. Core can open this file with its native append-before-edit flow.
    _create(data / 'bitcoin.conf',
            '# Additional Bitcoin Core options.\n'
            '# Network, RPC and storage policy are managed in Node Settings.\n')
    validate_user_config(data / 'bitcoin.conf')
    config = home / '.config'
    preferences = config / 'Bitcoin'
    preferences.mkdir(mode=0o700, parents=True, exist_ok=True)
    for directory in (config, preferences):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise RuntimeError('Core preferences directory is unsafe.')
    # Set defaults only when absent. Avoid deserializing custom upstream Qt
    # types (such as BitcoinUnit) in the system PySide runtime.
    suffix = '' if network == 'main' else '-' + network
    path = preferences / ('Bitcoin-Qt' + suffix + '.conf')
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1):
            raise RuntimeError('Core preferences file is unsafe.')
    _seed_controls(path)
    # The service has its own home. Give its native open-config action an editor
    # without modifying the desktop user's applications or an existing choice.
    _create(config / 'mimeapps.list',
            '[Default Applications]\ntext/plain=org.xfce.mousepad.desktop;\n')
    portal = config / 'xdg-desktop-portal'
    portal.mkdir(mode=0o700, exist_ok=True)
    info = portal.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise RuntimeError('Core desktop portal preferences are unsafe.')
    _create(portal / 'portals.conf','[preferred]\ndefault=gtk\n')
