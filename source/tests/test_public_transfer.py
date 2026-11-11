import importlib.machinery,importlib.util,os,tempfile,unittest
from pathlib import Path
path=Path(__file__).resolve().parents[1]/'runtime/usr/libexec/core-node-transfer'
loader=importlib.machinery.SourceFileLoader('transfer',str(path))
spec=importlib.util.spec_from_loader(loader.name,loader)
transfer=importlib.util.module_from_spec(spec);loader.exec_module(transfer)
class PublicTransfer(unittest.TestCase):
    def test_only_intentionally_shared_regular_single_link_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'shared';folder.mkdir()
            outside=root/'outside';outside.write_bytes(b'untouched');outside.chmod(0o600)
            (folder/'symlink').symlink_to(outside)
            os.link(outside,folder/'hardlink')
            os.mkfifo(folder/'pipe',0o600)
            (folder/'subfolder').mkdir()
            private=folder/'subfolder/nested';private.write_text('untouched');private.chmod(0o600)
            public=folder/'watch-only.dat';public.write_bytes(b'public fixture');public.chmod(0o600)
            transfer.share(folder,owners={os.getuid()},group=os.getgid())
            self.assertEqual(public.stat().st_mode&0o777,0o660)
            self.assertEqual(public.read_bytes(),b'public fixture')
            self.assertEqual(outside.stat().st_mode&0o777,0o600)
            self.assertEqual(private.stat().st_mode&0o777,0o600)
            transfer.share(folder,owners={os.getuid()},group=os.getgid())
            self.assertEqual(public.stat().st_mode&0o777,0o660)
    def test_other_owner_or_group_and_symlink_directory_are_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'shared';folder.mkdir()
            public=folder/'file';public.write_text('public');public.chmod(0o600)
            transfer.share(folder,owners=set(),group=os.getgid())
            self.assertEqual(public.stat().st_mode&0o777,0o600)
            transfer.share(folder,owners={os.getuid()},group=os.getgid()+1)
            self.assertEqual(public.stat().st_mode&0o777,0o600)
            link=root/'link';link.symlink_to(folder)
            with self.assertRaises(OSError):transfer.share(link,owners={os.getuid()},group=os.getgid())
if __name__=='__main__':unittest.main()
