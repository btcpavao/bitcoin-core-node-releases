"""Vault disk selection boundary tests; pure fixtures, no partitioning."""
import importlib.util,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('node_installer_disk',ROOT/'runtime/usr/lib/core-node-installer/disk_safety.py')
D=importlib.util.module_from_spec(spec);spec.loader.exec_module(D)

def disk():
    return {'name':'/dev/vda','type':'disk','tran':'virtio','ro':False,'rm':False,
        'size':48*1024**3,'serial':'CV_TEST_BIOS','wwn':None,'model':'VirtIO',
        'maj:min':'252:0','mountpoints':[None],'children':[]}

class DiskTests(unittest.TestCase):
    def check(self,node=None,**kw):
        return D.validate_tree(node or disk(),kw.get('sysfs','/sys/devices/pci/virtio/block/vda'),
            kw.get('holders',set()),kw.get('swaps',set()))
    def test_virtual_disk(self): self.assertEqual(self.check()['serial'],'CV_TEST_BIOS')
    def test_internal_sata(self):
        n=disk();n.update(name='/dev/sda',tran='sata');self.assertEqual(self.check(n)['name'],'/dev/sda')
    def test_nvme(self):
        n=disk();n.update(name='/dev/nvme0n1',tran='nvme');self.check(n)
    def test_usb(self):
        n=disk();n['tran']='usb'
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_usb_sysfs(self):
        with self.assertRaises(D.UnsafeDisk):self.check(sysfs='/sys/pci/usb1/1-2/block/vda')
    def test_readonly(self):
        n=disk();n['ro']=True
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_removable(self):
        n=disk();n['rm']=1
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_small(self):
        n=disk();n['size']=4*1024**3
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_no_identity(self):
        n=disk();n['serial']=''
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_whitespace_identity(self):
        n=disk();n['serial']='   '
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_partition(self):
        n=disk();n.update(name='/dev/vda1',type='part')
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_host_root(self):
        n=disk();n['mountpoints']=['/']
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_live_medium_mounted(self):
        n=disk();n['children']=[{'name':'/dev/vda1','type':'part','mountpoints':['/run/live/medium']}]
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_active_swap(self):
        with self.assertRaises(D.UnsafeDisk):self.check(swaps={'/dev/vda'})
    def test_holder(self):
        with self.assertRaises(D.UnsafeDisk):self.check(holders={'/dev/vda'})
    def test_mapped_child(self):
        n=disk();n['children']=[{'name':'/dev/dm-0','type':'crypt','mountpoints':[]}]
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_network(self):
        n=disk();n['tran']='iscsi'
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_changed_identity(self):
        n=disk();n['serial']='OTHER';self.assertNotEqual(self.check(n),self.check())
    def test_regular_file(self):
        with tempfile.NamedTemporaryFile() as f:
            with self.assertRaises((D.UnsafeDisk,OSError)):D.probe(f.name)
