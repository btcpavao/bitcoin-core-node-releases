"""Explicit, scoped, best-effort multi-pass deletion of selected Core wallets.

Thunar's Core directory stays read-only. The privileged helper only accepts
direct children of DATA/wallets containing wallet.dat, updates startup settings, and
temporarily stops Core for a controlled deletion. SSD/flash/journaling media
can preserve historical blocks; this cannot guarantee forensic erasure.
"""
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess

from state import DATA, load_setup, verify_data_mount
from wallet_startup import read_settings, clean_startup, WalletStartupError

WALLET_ROOT=DATA/'wallets'
SERVICE='bitcoin-core-node.service'
PASSES=3
CHUNK=1024*1024
MAX_FILES=4096
MAX_WALLETS=32
MAX_BATCH_BYTES=8*1024**3
MAX_BATCH_FILES=8192
MAX_BYTES=4*1024**3
MAX_DEPTH=5
ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'}

class WalletDeleteError(RuntimeError):
    pass

def validate_name(name):
    if not isinstance(name,str) or name in ('','.','..'):
        raise WalletDeleteError('Choose a named Bitcoin Core wallet folder.')
    encoded=name.encode('utf-8',errors='strict')
    if len(encoded)>128 or name.startswith('.') or name.startswith('-') or name.endswith(' '):
        raise WalletDeleteError('Unsupported Bitcoin Core wallet folder name.')
    if any(c in name for c in ('/','\\','\0')) or any(ord(c)<32 or ord(c)==127 for c in name):
        raise WalletDeleteError('Unsafe Bitcoin Core wallet folder name.')
    return name

def validate_inventory(name,root=WALLET_ROOT,uid=None):
    """Read-only, no-follow preflight; returns selected files + directories."""
    validate_name(name)
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise WalletDeleteError('Bitcoin Core wallet storage is unavailable.')
    directory=root/name
    base=os.lstat(directory)
    if not stat.S_ISDIR(base.st_mode) or os.path.ismount(directory):
        raise WalletDeleteError('The selected wallet must be an ordinary directory.')
    if uid is not None and base.st_uid!=uid:
        raise WalletDeleteError('Unexpected wallet owner; refusing to delete.')
    marker=directory/'wallet.dat'
    try:
        walletstat=os.lstat(marker)
        if not stat.S_ISREG(walletstat.st_mode) or walletstat.st_nlink!=1 or walletstat.st_size<=0:
            raise WalletDeleteError('Selected folder does not contain a normal Bitcoin Core wallet.dat.')
    except FileNotFoundError:
        raise WalletDeleteError('Selected folder does not contain Bitcoin Core wallet.dat.') from None
    files=[]
    directories=[]
    total=0
    for parent,subdirs,filenames in os.walk(directory,topdown=True,followlinks=False):
        current=Path(parent)
        depth=len(current.relative_to(directory).parts)
        if depth>MAX_DEPTH:
            raise WalletDeleteError('Wallet directory nesting exceeds the safe limit.')
        here=os.lstat(current)
        if not stat.S_ISDIR(here.st_mode) or here.st_dev!=base.st_dev or os.path.ismount(current):
            raise WalletDeleteError('Wallet folder contains a mount or unusual file.')
        if uid is not None and here.st_uid!=uid:
            raise WalletDeleteError('Unexpected file owner in wallet directory.')
        directories.append(current)
        for name in [*subdirs,*filenames]:
            target=current/name
            record=os.lstat(target)
            if record.st_dev!=base.st_dev or (uid is not None and record.st_uid!=uid):
                raise WalletDeleteError('Wallet files must belong to the same wallet filesystem and owner.')
            if not stat.S_ISDIR(record.st_mode) and not stat.S_ISREG(record.st_mode):
                raise WalletDeleteError('Wallet folder contains symbolic links or special files.')
            if stat.S_ISDIR(record.st_mode):
                if os.path.ismount(target):
                    raise WalletDeleteError('Wallet folder contains a nested filesystem mount.')
                continue
            if record.st_nlink!=1:
                raise WalletDeleteError('Wallet file has another hard link; refusing to overwrite it.')
            files.append((target,record))
            total+=record.st_size
            if total>MAX_BYTES or len(files)>MAX_FILES:
                raise WalletDeleteError('Wallet exceeds the safe deletion size limit.')
    if not any(p.name=='wallet.dat' for p,_ in files):
        raise WalletDeleteError('Bitcoin Core wallet.dat was not found.')
    return directory,base,files,sorted(directories,key=lambda p:len(p.parts),reverse=True),total

def wipe_file(path,expected,passes=PASSES):
    """Overwrite only a previously validated regular file, then unlink it."""
    if passes!=PASSES:
        raise WalletDeleteError('Unsupported overwrite profile.')
    flags=os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC
    fd=os.open(path,flags)
    try:
        before=os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_ino!=expected.st_ino
            or before.st_dev!=expected.st_dev or before.st_size!=expected.st_size
            or before.st_nlink!=1):
            raise WalletDeleteError('Wallet file changed during deletion.')
        for pass_number in range(passes+1):
            os.lseek(fd,0,os.SEEK_SET)
            left=before.st_size
            while left>0:
                size=min(left,CHUNK)
                data=(b'\0'*size) if pass_number==passes else os.urandom(size)
                view=memoryview(data)
                while view:
                    written=os.write(fd,view)
                    if written<=0:raise OSError('Write did not complete')
                    view=view[written:]
                left-=size
            os.fsync(fd)
        after=os.lstat(path)
        if after.st_ino!=before.st_ino or after.st_dev!=before.st_dev:
            raise WalletDeleteError('Wallet file was replaced during deletion.')
        os.ftruncate(fd,0)
        os.fsync(fd)
        os.unlink(path)
    finally:
        os.close(fd)

def wipe_directory(name,root=WALLET_ROOT,uid=None):
    directory,stamp,files,dirs,_=validate_inventory(name,root,uid)
    # Revalidate the entire inventory before the first destructive write.
    assert os.lstat(directory).st_ino==stamp.st_ino
    for path,info in files:
        now=os.lstat(path)
        if now.st_ino!=info.st_ino or now.st_size!=info.st_size or now.st_dev!=info.st_dev:
            raise WalletDeleteError('Wallet changed after selection.')
    for path,info in files:
        wipe_file(path,info)
    for folder in dirs:
        os.rmdir(folder)
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
    return len(files)

def command(*args,timeout=330):
    result=subprocess.run(['/usr/bin/systemctl',*args],env=ENV,capture_output=True,timeout=timeout)
    if result.returncode:
        raise WalletDeleteError('Bitcoin Core service change failed. Wallet files have not been automatically recovered.')
    if args==('stop',SERVICE):
        status=subprocess.run(['/usr/bin/systemctl','show','--property=Result','--value',SERVICE],
                              env=ENV,capture_output=True,timeout=10)
        if status.returncode or status.stdout.strip()!=b'success':
            raise WalletDeleteError('Bitcoin Core did not exit cleanly. No wallet was deleted. Please review the Node log before retrying.')

def running():
    result=subprocess.run(['/usr/bin/systemctl','is-active','--quiet',SERVICE],
                          env=ENV,capture_output=True,timeout=10)
    return result.returncode==0

def request_names(request):
    """Accept one exact legacy wallet or a bounded, unique wallet-name batch."""
    if not isinstance(request,dict):
        raise WalletDeleteError('Invalid wallet deletion request.')
    if request.get('confirmed') is not True or request.get('profile')!='three-pass-best-effort':
        raise WalletDeleteError('Wallet deletion was not explicitly confirmed.')
    if set(request)=={'wallet','confirmed','profile'}:
        values=[request['wallet']]
    elif set(request)=={'wallets','confirmed','profile'}:
        values=request['wallets']
    else:
        raise WalletDeleteError('Invalid wallet deletion request.')
    if not isinstance(values,list) or not 1<=len(values)<=MAX_WALLETS:
        raise WalletDeleteError('Choose between one and 32 wallet folders.')
    names=[validate_name(value) for value in values]
    if len(set(names))!=len(names):
        raise WalletDeleteError('The same wallet folder cannot be selected twice.')
    return names


def perform(request):
    """Run inside the authenticated Node administrator; never trust GUI paths."""
    if os.geteuid()!=0:
        raise WalletDeleteError('This operation requires the Node administrator.')
    user=pwd.getpwnam('node')
    if int(os.environ.get('PKEXEC_UID','-1'))!=user.pw_uid:
        raise WalletDeleteError('Only the active Node desktop can request wallet removal.')

    names=request_names(request)
    verify_data_mount(load_setup())
    walletuid=pwd.getpwnam('bitcoinnode').pw_uid

    # Verify ALL selected wallets BEFORE stopping Core or performing ANY write.
    # The batch fails closed if a single wallet is invalid or too large.
    inventories=[]
    total_bytes=0
    total_files=0
    for name in names:
        directory,stamp,files,dirs,size=validate_inventory(name,WALLET_ROOT,walletuid)
        total_bytes+=size
        total_files+=len(files)
        if total_bytes>MAX_BATCH_BYTES or total_files>MAX_BATCH_FILES:
            raise WalletDeleteError('Selected wallet batch exceeds the safe deletion limit.')
        inventories.append((name,directory,stamp))

    settings=WALLET_ROOT.parent/'settings.json'
    try:read_settings(settings,walletuid)
    except WalletStartupError as exc:raise WalletDeleteError(str(exc)) from exc
    active=running()
    # A synchronous stop also waits out an already-running shutdown. Core flushes
    # every loaded wallet and its settings before any database is overwritten.
    command('stop',SERVICE)
    if running():
        raise WalletDeleteError('Bitcoin Core did not finish shutting down. No wallet was deleted.')

    removed=[]
    count=0
    try:
        # Verify every selected wallet AGAIN after Core has stopped and before
        # starting any irreversible overwrite. Do not allow changed entries.
        for name,directory,stamp in inventories:
            now=os.lstat(directory)
            if now.st_ino!=stamp.st_ino or now.st_dev!=stamp.st_dev:
                raise WalletDeleteError('One selected wallet folder changed before deletion.')
            validate_inventory(name,WALLET_ROOT,walletuid)

        try:clean_startup(settings,WALLET_ROOT,walletuid,selected=names)
        except WalletStartupError as exc:raise WalletDeleteError(str(exc)) from exc
        for name,_,_ in inventories:
            count+=wipe_directory(name,WALLET_ROOT,walletuid)
            removed.append(name)
    except Exception:
        # An interrupted overwrite is not recoverable. Do not restart Core
        # automatically into a possibly incomplete wallet database.
        raise
    if active:
        try:command('start',SERVICE,timeout=120)
        except WalletDeleteError as exc:
            raise WalletDeleteError('Wallets removed, but Bitcoin Core could not restart. Open Bitcoin Core manually.') from exc

    return {'ok':True,'removed_wallets':removed,'removed_wallet':removed[0] if len(removed)==1 else None,
            'files':count,'note':'Best effort: SSDs, filesystem journals, snapshots and prior backups may retain older copies.'}
