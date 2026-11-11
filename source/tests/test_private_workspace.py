"""Reject unsafe storage metadata before any private file operation starts."""
import json,os,stat,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import private_workspace as w

class WorkspacePolicy(unittest.TestCase):
 def test_power_occupancy_counts_every_entry_without_following_links(self):
  with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp,patch.object(w,'check_storage',return_value=Path(tmp)),patch.object(w,'check_psbt_storage',return_value=Path(tmp)):
   folder=Path(tmp)
   self.assertFalse(w.has_contents())
   for name,kind in [('visible.txt','file'),('.hidden','file'),('empty-folder','directory'),('dangling','link')]:
    path=folder/name
    if kind=='directory':path.mkdir()
    elif kind=='link':path.symlink_to(folder/'does-not-exist')
    else:path.touch()
    self.assertTrue(w.has_contents(),name)
    if kind=='directory':path.rmdir()
    else:path.unlink()
   self.assertFalse(w.has_contents())
 def test_unavailable_workspace_does_not_skip_power_warnings(self):
  with patch.object(w,'check_storage',side_effect=w.WorkspaceError('unavailable')):
   self.assertTrue(w.has_contents())
  with patch.object(w,'check_storage',return_value=Path('/does-not-exist-node-workspace')):
   self.assertTrue(w.has_contents())
 def test_private_gui_does_not_inherit_an_unavailable_locale(self):
  with patch.dict(os.environ,{'LANG':'absent.UTF-8','LC_ALL':'absent.UTF-8'}), \
   patch.object(w,'check_storage'),patch.object(w.os,'umask'),patch.object(w.resource,'setrlimit'):
   env=w.private_environment()
  self.assertEqual(env['LANG'],'C.UTF-8')
  self.assertEqual(env['LC_ALL'],'C.UTF-8')
  self.assertEqual(env['XDG_CONFIG_HOME'],str(w.USER/'config'))
  result=w.subprocess.run(['locale','charmap'],env=env,capture_output=True,text=True,check=True)
  self.assertEqual(result.stdout.strip(),'UTF-8')
  self.assertNotIn('Cannot set',result.stderr)
 def test_mount_swap_and_permissions_fail_closed(self):
  node=types.SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())
  core=types.SimpleNamespace(pw_gid=os.getgid())
  with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
   root=Path(tmp);private=root/'workspace';private.mkdir(mode=0o700);private.chmod(0o2770)
   user=root/'user';user.mkdir(mode=0o700);export=user/'export';export.mkdir(mode=0o700)
   mount={'target':str(root),'fstype':'tmpfs','options':'rw,noswap,nodev,nosuid,noexec'}
   original_read=Path.read_text;original_lstat=Path.lstat
   def read(path,*a,**kw):
    if str(path)=='/proc/swaps':return swaps[0]
    return original_read(path,*a,**kw)
   def lstat(path):
    info=original_lstat(path)
    if path==root:return types.SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=0,st_dev=info.st_dev)
    return info
   swaps=['Filename Type Size Used Priority\n']
   with patch.multiple(w,ROOT=root,PRIVATE=private,USER=user,EXPORT=export), \
    patch.object(w.pwd,'getpwnam',side_effect=lambda n:node if n=='node' else core), \
    patch.object(Path,'is_file',return_value=True),patch.object(Path,'read_text',read), \
    patch.object(Path,'lstat',lstat),patch.object(w.subprocess,'check_output',side_effect=lambda *a,**kw:json.dumps({'filesystems':[mount]})):
    self.assertEqual(w.check_storage(),private)
    for option in ('noswap','nodev','nosuid','noexec'):
     old=mount['options'];mount['options']=old.replace(option,'')
     with self.assertRaises(w.WorkspaceError):w.check_storage()
     mount['options']=old
    mount['fstype']='ext4'
    with self.assertRaises(w.WorkspaceError):w.check_storage()
    mount['fstype']='tmpfs';swaps[0]+='/swapfile file 100 0 -2\n'
    with self.assertRaises(w.WorkspaceError):w.check_storage()
    swaps[0]='Filename Type Size Used Priority\n';private.chmod(0o2777)
    with self.assertRaises(w.WorkspaceError):w.check_storage()
    private.chmod(0o2770);private.rmdir();private.symlink_to(user)
    with self.assertRaises(w.WorkspaceError):w.check_storage()

if __name__=='__main__':unittest.main()
