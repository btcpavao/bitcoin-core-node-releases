#!/usr/bin/python3
"""Offline, hash-pinned feature update for the tested 32.1 Node installation.

Only application files/boot units listed here may change. No user configuration,
wallet, chainstate, login or device data is copied. Restart to reload the UI.
"""
import contextlib,fcntl,hashlib,json,os,stat,subprocess,sys,tempfile
from pathlib import Path
FILES={
 'usr/lib/bitcoin-core-node/backup_restore_ui.py':0o644,
 'usr/lib/bitcoin-core-node/encrypted_transfer.py':0o644,
 'usr/lib/bitcoin-core-node/watch_backup.py':0o644,
 'usr/lib/bitcoin-core-node/watch_backup_ui.py':0o644,
 'usr/lib/bitcoin-core-node/watch_wallet_probe.py':0o644,
 'usr/lib/bitcoin-core-node/chain_ui.py':0o644,
 'usr/local/bin/core-node-taskbar':0o755,

 'usr/lib/bitcoin-core-node/settings_snapshot.py':0o644,
 'usr/lib/bitcoin-core-node/settings_restore.py':0o644,
 'usr/lib/bitcoin-core-node/settings_snapshot_ui.py':0o644,
 'usr/libexec/core-node-settings-restore':0o755,
 'etc/systemd/system/core-node-settings-restore.service':0o644,
 'etc/systemd/system/core-node-settings-time.service':0o644,
 'etc/systemd/system/NetworkManager.service.d/30-settings-restore.conf':0o644,
 'etc/systemd/system/bitcoin-core-node-policy.service.d/30-settings-restore.conf':0o644,
 'etc/systemd/system/bitcoin-core-node.service.d/30-settings-restore.conf':0o644,
 'usr/libexec/core-node-admin':0o755,
 'usr/lib/bitcoin-core-node/ui.py':0o644,
 'usr/lib/bitcoin-core-node/launcher_ui.py':0o644,
}
BASE_FILES={'usr/libexec/core-node-admin','usr/lib/bitcoin-core-node/ui.py','usr/lib/bitcoin-core-node/launcher_ui.py','usr/lib/bitcoin-core-node/chain_ui.py','usr/local/bin/core-node-taskbar'}
RECORD=Path('/var/lib/bitcoin-core-node/maintenance/settings-snapshot-20261106')
UNITS=('core-node-settings-restore.service','core-node-settings-time.service')
LOCKS=('/run/lock/bitcoin-core-node-admin.lock','/run/lock/core-node-software.lock')
def hash_bytes(data):return hashlib.sha256(data).hexdigest()
def trusted(path,directory=False):
 info=path.lstat();expected=stat.S_ISDIR if directory else stat.S_ISREG
 if not expected(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or (not directory and info.st_nlink!=1):raise RuntimeError('Unsafe installed path: '+str(path))
 return info

def atomic(path,data,mode):
 fd,name=tempfile.mkstemp(prefix='.settings-update-',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as stream:
   os.fchmod(stream.fileno(),mode);stream.write(data);stream.flush();os.fsync(stream.fileno())
  os.replace(name,path)
  fd=os.open(path.parent,os.O_DIRECTORY|os.O_NOFOLLOW)
  try:os.fsync(fd)
  finally:os.close(fd)
 finally:Path(name).unlink(missing_ok=True)

def command(*args):return subprocess.run(['/usr/bin/systemctl',*args],check=True,capture_output=True,timeout=30)

def main():
 if os.geteuid()!=0 or sys.argv[1:] not in ([],['--check']):raise RuntimeError('Please run sudo python3 install.py [--check] on the installed Node.')
 check=sys.argv[1:]==['--check']
 trusted(Path('/etc/bitcoin-core-node/installed'))
 if 'VERSION_ID="13"' not in Path('/etc/os-release').read_text():raise RuntimeError('This update requires the tested Debian 13 Node.')
 bundle=Path(__file__).resolve().parent
 metadata=json.loads((bundle/'manifest.json').read_bytes())
 if metadata.get('format')!='core-node-settings-update-20261106' or set(metadata.get('files',{}))!=set(FILES):raise RuntimeError('Invalid feature-update manifest.')
 payload={};original={};modes={}
 for name in FILES:
  p=bundle/'files'/name;info=p.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>1024*1024:raise RuntimeError('Unsafe update payload.')
  raw=p.read_bytes()
  if hash_bytes(raw)!=metadata['files'][name]['new_sha256']:raise RuntimeError('Update payload checksum mismatch.')
  if name.endswith('.py') or name.startswith(('usr/libexec/','usr/local/bin/')):compile(raw,name,'exec')
  payload[name]=raw
 with contextlib.ExitStack() as stack:
  for lock in LOCKS:
   fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);stack.callback(os.close,fd)
   info=os.fstat(fd)
   if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1:raise RuntimeError('Unsafe maintenance lock.')
   fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  for unit in ('core-node-software-check.service','core-node-software-install.service'):
   if subprocess.run(['/usr/bin/systemctl','is-active','--quiet',unit],timeout=5).returncode==0:raise RuntimeError('Software maintenance is active. Please finish it first.')
  for name in FILES:
   target=Path('/')/name
   for parent in target.parents:
    if parent.exists():trusted(parent,True)
   if target.exists() or target.is_symlink():
    info=trusted(target);raw=target.read_bytes();modes[name]=stat.S_IMODE(info.st_mode)
    if hash_bytes(raw) not in (metadata['files'][name]['base_sha256'],metadata['files'][name]['new_sha256']):raise RuntimeError('Unknown installed revision: '+name+'. No files changed.')
    original[name]=raw
   else:
    if name in BASE_FILES:raise RuntimeError('Required Node application is missing.')
    original[name]=None;modes[name]=FILES[name]
  if check:print('CHECK PASSED: known Node revision and all update payloads verified. No application files changed.');return
  already=all(original[k]==payload[k] for k in FILES)
  RECORD.parent.mkdir(mode=0o700,exist_ok=True);trusted(RECORD.parent,True)
  RECORD.mkdir(mode=0o700,exist_ok=True);trusted(RECORD,True)
  for name,raw in original.items():
   backup=RECORD/(name.replace('/','_')+'.previous')
   if raw is not None and not backup.exists():atomic(backup,raw,0o600)
  changed=[]
  try:
   for name,raw in payload.items():
    path=Path('/')/name
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o755)
    if original[name]!=raw:changed.append(name);atomic(path,raw,FILES[name])
   for name,raw in payload.items():
    if (Path('/')/name).read_bytes()!=raw:raise RuntimeError('Installed update verification failed.')
   command('daemon-reload');command('enable',*UNITS)
  except BaseException:
   for name in reversed(changed):
    path=Path('/')/name
    if original[name] is None:path.unlink(missing_ok=True)
    else:atomic(path,original[name],modes[name])
   subprocess.run(['/usr/bin/systemctl','daemon-reload'],capture_output=True,timeout=30)
   raise
  atomic(RECORD/'status.json',(json.dumps(dict(complete=True,source_commit=metadata['source_commit'],files=list(FILES)))+'\n').encode(),0o600)
 print('ALREADY INSTALLED.' if already else 'UPDATE COMPLETE: grouped backup/restore and taskbar fixes installed and verified.')
 print('Login, network settings, wallets and blockchain were not changed. Please restart normally to load the new Settings button.')

if __name__=='__main__':
 try:main()
 except Exception as exc:
  print('Update refused or rolled back: '+str(exc),file=sys.stderr);sys.exit(1)
