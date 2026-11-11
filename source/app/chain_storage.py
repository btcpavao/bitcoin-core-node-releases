"""Allocated chain data + genuinely available disk space, never whole-disk usage.

Read-only metadata through the already verified Core Files view. No wallet reads,
new permissions, RPC wallet calls or privileged helper. A bounded child process
counts the same roots as blockchain backup; the GUI worker caches that estimate.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import time

from chain_backup import ROOTS, MAX_FILES
from state import DATA, load_setup, verify_data_mount
from file_browser import check_core_view

CACHE_SECONDS = 15
SCAN_SECONDS = 3
SCAN_PROCESS_TIMEOUT = 5
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_cache = None
_lock = threading.Lock()


def context():
    """A missing external disk or Files view must not fall back to the root disk."""
    setup = load_setup()
    network = setup['network']
    if network not in ('main', 'signet', 'regtest'):
        raise ValueError('Unknown chain')
    mount = verify_data_mount(setup, DATA)
    view = check_core_view()
    disk_info, view_info = os.stat(DATA, follow_symlinks=False), os.stat(view, follow_symlinks=False)
    if not stat.S_ISDIR(disk_info.st_mode) or not stat.S_ISDIR(view_info.st_mode):
        raise ValueError('No chain directory')
    identity = [network, setup.get('data_uuid'), mount.get('uuid'), mount.get('target'),
                disk_info.st_dev, disk_info.st_ino, view_info.st_dev, view_info.st_ino]
    return network, view, identity


def allocated_chain_bytes(view: Path, network: str, *, deadline=None, max_entries=MAX_FILES):
    """Count allocated bytes, not apparent length (important for preallocated files).

    Never follow symlinks or cross nested filesystems. A file disappearing during
    normal Core compaction is skipped; this is a refreshed estimate, not a backup.
    Other unsafe/unreadable entries fail closed rather than producing a low total.
    """
    if network not in ('main', 'signet', 'regtest'):
        raise ValueError('Unsupported chain')
    deadline = time.monotonic() + SCAN_SECONDS if deadline is None else deadline
    visited = 0
    def check_time():
        if time.monotonic() > deadline:
            raise TimeoutError('Chain-size scan exceeded its metadata budget')
    def walk(fd, device):
        nonlocal visited
        check_time()
        info = os.fstat(fd)
        if info.st_dev != device:
            raise ValueError('Nested chain mount')
        total = info.st_blocks * 512
        with os.scandir(fd) as entries:
            for entry in entries:
                check_time(); visited += 1
                if visited > max_entries:
                    raise ValueError('Too many chain files')
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if info.st_dev != device:
                    raise ValueError('Nested chain mount')
                if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    total += info.st_blocks * 512
                elif stat.S_ISDIR(info.st_mode):
                    try:child = os.open(entry.name, DIR_FLAGS, dir_fd=fd)
                    except FileNotFoundError:continue
                    try:total += walk(child, device)
                    finally:os.close(child)
                else:
                    raise ValueError('Unsupported link or special file in chain data')
        return total
    root = os.open(view, DIR_FLAGS)
    try:
        device = os.fstat(root).st_dev
        if network != 'main':
            try:child = os.open(network, DIR_FLAGS, dir_fd=root)
            except FileNotFoundError:return 0
            os.close(root); root = child
            if os.fstat(root).st_dev != device:
                raise ValueError('Nested network mount')
        total = 0
        for name in ROOTS:
            check_time()
            try:child = os.open(name, DIR_FLAGS, dir_fd=root)
            except FileNotFoundError:continue  # Fresh Core has no chain files yet.
            try:total += walk(child, device)
            finally:os.close(child)
        return total
    finally:os.close(root)


def measure():
    network, view, before = context()
    used = allocated_chain_bytes(view, network)
    _, _, after = context()
    if before != after:
        raise ValueError('Chain storage changed during measurement')
    return dict(identity=before, used=used)


def reading(used, free):
    """The current chain capacity excludes Debian, wallets, logs and reserved space."""
    if type(used) is not int or type(free) is not int or min(used, free) < 0:
        raise ValueError('Invalid chain allocation')
    total = used + free
    # No allocatable bytes is a full disk, even on a not-yet-started node.
    percent = 100 * used / total if total else 100.0
    percent = round(percent, 1)
    if free > 0:percent = min(percent, 99.9)  # Do not round a nearly full disk to full.
    return dict(scope='blockchain', used=used, free=free, total=total,
                used_percent=percent, free_percent=round(100-percent, 1))


def storage_usage():
    """Called in a Qt worker, never on the GUI thread. Cached scan, live free space."""
    global _cache
    try:
        _, _, key = context()
        with _lock:
            now = time.monotonic()
            if _cache is None or _cache[0] != key or now - _cache[1] >= CACHE_SECONDS:
                process = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--measure'],
                    capture_output=True, text=True, check=True, timeout=SCAN_PROCESS_TIMEOUT,
                    env=dict(PATH='/usr/bin:/bin', LANG='C.UTF-8', LC_ALL='C.UTF-8'))
                if len(process.stdout) > 4096:
                    raise ValueError('Unexpected metadata result')
                result = json.loads(process.stdout)
                if (set(result) != {'identity','used'} or result['identity'] != key
                        or type(result['used']) is not int or result['used'] < 0):
                    raise ValueError('Chain identity changed')
                _cache = (key, time.monotonic(), result['used'])
            _, _, final_key = context()
            if key != final_key:
                raise ValueError('Data drive changed')
            fs = os.statvfs(DATA)
            free = fs.f_bavail * fs.f_frsize
            if fs.f_frsize <= 0 or fs.f_blocks < 0 or free < 0 or free > fs.f_blocks * fs.f_frsize:
                raise ValueError('Invalid filesystem counters')
            result = reading(_cache[2], free)
            result['sample_age_seconds'] = max(0, round(time.monotonic() - _cache[1], 1))
            return result
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError):
        _cache = None
        return None


if __name__ == '__main__':
    if sys.argv[1:] != ['--measure']:
        raise SystemExit(2)
    try:
        print(json.dumps(measure(), separators=(',',':')))
    except Exception:
        # Never echo path names, wallet names or other local details to Home.
        raise SystemExit(1) from None
