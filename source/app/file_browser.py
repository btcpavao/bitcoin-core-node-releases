"""The desktop can inspect live Core data through a fixed read-only view."""
import json
from pathlib import Path
import subprocess

CORE_DATA = Path('/var/lib/bitcoin-core-node/data')
CORE_VIEW = Path('/run/core-node-files/Core')


class BrowserError(RuntimeError):
    pass


def check_core_view():
    try:
        rows = json.loads(subprocess.check_output(
            ['/usr/bin/findmnt', '-J', '-M', str(CORE_VIEW), '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS'],
            text=True, stderr=subprocess.DEVNULL, timeout=10))['filesystems']
        if (len(rows) != 1 or rows[0]['target'] != str(CORE_VIEW)
                or rows[0]['source'] != str(CORE_DATA) or rows[0]['fstype'] != 'fuse.bindfs'
                or not {'ro', 'nodev', 'nosuid', 'noexec'}.issubset(rows[0]['options'].split(','))
                or CORE_VIEW.is_symlink()):
            raise ValueError()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise BrowserError('Core files are unavailable. Please check the data drive or restart Node.') from None
    return CORE_VIEW


def open_core_files():
    subprocess.Popen(['/usr/bin/thunar', str(check_core_view())])
