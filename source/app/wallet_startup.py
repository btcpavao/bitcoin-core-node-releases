"""Safely edit Core's startup list only while Core is stopped.

Missing external wallets and existing but damaged directories are preserved.
Callers must first verify the managed data mount and stop Core (or run before
execing it). No wallet database is opened or modified here.
"""
import json
import os
from pathlib import Path
import stat
import tempfile

MAX_SETTINGS_BYTES = 4 * 1024 * 1024


class WalletStartupError(RuntimeError):
    pass


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate settings key')
        result[key] = value
    return result


def read_settings(path, uid):
    path = Path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        raise WalletStartupError('Core startup settings cannot be opened safely.') from exc
    try:
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
                    or info.st_nlink != 1 or info.st_size > MAX_SETTINGS_BYTES):
                raise WalletStartupError('Core startup settings have unsafe ownership or file type.')
            record = json.loads(stream.read(MAX_SETTINGS_BYTES + 1), object_pairs_hook=_object)
        if not isinstance(record, dict):
            raise ValueError('Expected a settings object')
        if 'wallet' in record and (not isinstance(record['wallet'], list)
                or any(not isinstance(item, str) for item in record['wallet'])):
            raise ValueError('Invalid wallet startup list')
    except (ValueError, UnicodeError) as exc:
        raise WalletStartupError('Core startup settings are invalid. No wallet was deleted.') from exc
    return record, info


def _local_name(entry, root):
    path = Path(entry)
    if '..' in path.parts or not path.parts:
        return None
    if path.is_absolute():
        if path.parent != root:
            return None
    elif len(path.parts) != 1:
        return None
    name = path.name
    if name in ('', '.', '..') or '/' in name or '\\' in name:
        return None
    return name


def _replace(path, record, info):
    fd, temporary = tempfile.mkstemp(prefix='.node-startup-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode) & 0o600)
            os.fchown(stream.fileno(), info.st_uid, info.st_gid)
            json.dump(record, stream, ensure_ascii=False, sort_keys=True, indent=4)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        current = path.lstat()
        if (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) != (
                info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size):
            raise WalletStartupError('Core startup settings changed during maintenance.')
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clean_startup(path, root, uid, *, selected=(), missing=False):
    """Remove selected local wallets or absent direct folders; preserve all else."""
    path, root = Path(path), Path(root)
    record, info = read_settings(path, uid)
    if record is None or 'wallet' not in record:
        return []
    if root.is_symlink() or not root.is_dir():
        raise WalletStartupError('Managed wallet storage is unavailable.')
    removed, kept = [], []
    for entry in record['wallet']:
        name = _local_name(entry, root)
        remove = name is not None and name in selected
        if missing and name is not None:
            try:
                (root / name).lstat()
            except FileNotFoundError:
                remove = True
        (removed if remove else kept).append(entry)
    if removed:
        record['wallet'] = kept
        _replace(path, record, info)
    return removed
