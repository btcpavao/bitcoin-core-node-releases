"""Resource locks for the authenticated broker; no authorization is bypassed.

Only read-only configuration exports/previews/status avoid the Core lifecycle
lock. All mutations retain it. A second reader lock serializes configuration
changes against exports; it is independent of blockchain I/O.
"""
from contextlib import contextmanager,ExitStack
import fcntl,os,stat
from pathlib import Path

class OperationBusy(RuntimeError):pass

def resources(action):
    read_config=action in ('settings-backup','core-settings-backup','settings-preview','core-settings-preview','settings-status','core-settings-status')
    result=[]
    if not read_config:result.append(('bitcoin-core-node-admin.lock',fcntl.LOCK_EX))
    if read_config or action in ('chain-import','configure','time-settings','keyboard-settings','debian-updates','software-install','core-update','reboot','poweroff','settings-import','core-settings-import','settings-cancel','core-settings-cancel'):
        result.append(('core-node-configuration.lock',fcntl.LOCK_SH if read_config else fcntl.LOCK_EX))
    return result

@contextmanager
def guard(action,directory=Path('/run/lock')):
    with ExitStack() as stack:
        for name,mode in resources(action):
            fd=os.open(directory/name,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
            stack.callback(os.close,fd);info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1 or info.st_mode&0o022:
                raise OperationBusy('Unsafe maintenance lock; no operation started.')
            try:fcntl.flock(fd,mode|fcntl.LOCK_NB)
            except BlockingIOError:
                raise OperationBusy('A conflicting Core operation is running. Keep using Settings or back up Core/Node configuration. Watch-only transfer needs Core running; start it manually after the blockchain backup.') from None
        yield
