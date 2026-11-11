"""Discover the Home backup shortcut without inspecting wallets or network secrets.

The installer records metadata for a small set of non-secret default preferences.
The desktop compares them read-only and asks NetworkManager only for connection
types/timestamps. A one-way user-owned flag keeps the shortcut after first use.
This is navigation state, NOT a backup-completeness or backup-health indicator.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess

BASELINE = Path('/etc/bitcoin-core-node/home-defaults.json')
INSTALLED = Path('/etc/bitcoin-core-node/installed')
CORE_VIEW = Path('/run/core-node-files/Core')
PREFERENCES = (
    'etc/bitcoin-core-node/setup.json',
    'etc/default/keyboard',
    'etc/core-display-scale.conf',
    'etc/timezone',
    'etc/lightdm/lightdm.conf.d/99-node-login.conf',
    'etc/bitcoin-core-node/passwordless-login',
    'etc/systemd/timesyncd.conf',
)
LIMIT = 1024 * 1024
ENV = dict(PATH='/usr/sbin:/usr/bin:/sbin:/bin', LANG='C', LC_ALL='C')


def regular_bytes(path: Path, limit: int = LIMIT) -> bytes | None:
    """Never follow an unexpected link or block on a FIFO/device."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('Unexpected preference file')
        raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('Preference exceeds metadata limit')
        return raw


def preferences(root: Path = Path('/'), home: Path = Path('/home/node')) -> dict:
    """No shadow, wireless secrets, VPN keys, database data or wall-clock value."""
    result = {}
    for relative in PREFERENCES:
        # Some ordinary OS preference files are intentionally root-readable
        # only (e.g. LightDM's login mode). Both installer and desktop can stat
        # them. Never read their contents or loosen their permissions.
        try:
            info = (root / relative).lstat()
        except FileNotFoundError:
            result[relative] = None
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Unexpected preference file type')
        result[relative] = [info.st_size, info.st_mtime_ns]
    localtime = root / 'etc/localtime'
    result['timezone-link'] = os.readlink(localtime) if localtime.is_symlink() else None
    result['ntp-enabled'] = os.path.islink(root / 'etc/systemd/system/sysinit.target.wants/systemd-timesyncd.service')
    raw = regular_bytes(home / '.config/bitcoin-core-node/pointer.json')
    # An automatically created empty mouse-preferences file is not customization.
    devices = json.loads(raw).get('devices', {}) if raw else {}
    result['pointer-devices'] = hashlib.sha256(json.dumps(devices, sort_keys=True).encode()).hexdigest()
    return result


def capture_defaults() -> None:
    """Called once inside the installer's new target, never at desktop startup."""
    if os.geteuid() != 0 or not INSTALLED.is_file():
        raise RuntimeError('A new installed target is required')
    data = json.dumps(dict(version=2, preferences=preferences()), sort_keys=True).encode() + b'\n'
    fd = os.open(BASELINE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.fchmod(stream.fileno(), 0o644)


def network_customized(run=subprocess.run) -> bool:
    # No SSIDs, addresses, passwords or other profile contents are requested.
    result = run(['/usr/bin/nmcli', '--wait', '1', '-t', '-f', 'TYPE,TIMESTAMP',
                  'connection', 'show'], capture_output=True, text=True, timeout=2, env=ENV)
    if result.returncode:
        return False
    for line in result.stdout[:32768].splitlines():
        kind, _, timestamp = line.partition(':')
        if kind in ('802-11-wireless', 'wifi', 'vpn', 'wireguard', 'bluetooth'):
            return True
        # NM may create an unused wired profile at boot. That alone is not use.
        if kind in ('802-3-ethernet', 'ethernet') and timestamp.isdigit() and int(timestamp) > 0:
            return True
    return False


def bluetooth_customized(run=subprocess.run) -> bool:
    result = run(['/usr/bin/bluetoothctl', 'devices', 'Paired'],
                 capture_output=True, text=True, timeout=2, env=ENV)
    return result.returncode == 0 and any(line.startswith('Device ') for line in result.stdout[:32768].splitlines())


class BackupPresence:
    def __init__(self, *, root=Path('/'), home=None, core_view=CORE_VIEW):
        self.root = Path(root)
        self.home = Path.home() if home is None else Path(home)
        self.core_view = Path(core_view)
        self.marker = self.home / '.local/state/bitcoin-core-node/home-backup.json'
        self.visible = False

    @property
    def installed(self):
        return (self.root / str(INSTALLED).lstrip('/')).is_file()

    def remembered(self) -> bool:
        if not self.installed:
            return False
        try:
            raw = regular_bytes(self.marker, 256)
            value = json.loads(raw) if raw else {}
            return value == {'version': 1, 'visible': True}
        except (OSError, ValueError, TypeError):
            return False

    def remember(self) -> bool:
        self.visible = True
        if not self.installed:
            return True
        try:
            # Run only with the desktop's own privileges. No root helper/action.
            home_info = self.home.lstat()
            if not stat.S_ISDIR(home_info.st_mode) or home_info.st_uid != os.geteuid():
                return True
            for relative in ('.local', '.local/state', '.local/state/bitcoin-core-node'):
                path = self.home / relative
                if path.is_symlink():
                    return True
                path.mkdir(mode=0o700, exist_ok=True)
                info = path.lstat()
                # Debian may create ~/.local as 0775 for the user's own
                # primary group. This boolean has no authorization meaning;
                # refuse foreign ownership/groups and world-writable paths.
                unsafe_write = bool(info.st_mode & 0o002 or
                                    (info.st_mode & 0o020 and info.st_gid != os.getegid()))
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or unsafe_write:
                    return True
            fd = os.open(self.marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(b'{"version":1,"visible":true}\n'); stream.flush(); os.fsync(stream.fileno())
        except (OSError, ValueError):
            pass  # An inaccessible preference must not block Home or any backup.
        return True

    def check(self) -> bool:
        if not self.installed:
            return False
        if self.visible or self.remembered():
            self.visible = True
            return True
        baseline = self.root / str(BASELINE).lstrip('/')
        try:
            raw = regular_bytes(baseline, 16384)
            # Older installations have no factory record. Never snapshot their
            # already-customized configuration as a new clean default.
            if raw is None:
                return self.remember()
            data = json.loads(raw)
            if data.get('version') != 2 or not isinstance(data.get('preferences'), dict):
                return self.remember()
            if preferences(self.root, self.home) != data['preferences']:
                return self.remember()
        except (OSError, ValueError, TypeError, AttributeError):
            pass  # Failed metadata polling is not proof of a user change.
        try:
            # Existence only; never open wallet.dat or scan blockchain contents.
            if any((self.core_view / name).is_dir() for name in ('chainstate', 'blocks', 'signet/chainstate', 'regtest/chainstate')):
                return self.remember()
            wallets = self.core_view / 'wallets'
            if wallets.is_dir() and next(wallets.iterdir(), None) is not None:
                return self.remember()
        except OSError:
            pass
        for probe in (network_customized, bluetooth_customized):
            try:
                if probe():
                    return self.remember()
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        return False


def remember_local_use() -> None:
    """Successful managed actions notify the same flag; never write on the host."""
    if pwd.getpwuid(os.getuid()).pw_name == 'node':
        BackupPresence().remember()
