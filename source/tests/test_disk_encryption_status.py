"""Encryption status must describe backing storage, not just mapper names."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import disk_encryption as disk


class DiskEncryptionStatus(unittest.TestCase):
    def check(self,rows):
        with patch.object(disk.Path,'read_text',return_value='root=UUID=fixture quiet splash'),patch.object(disk.subprocess,'run',side_effect=[Mock(stdout='/dev/mapper/root\n'),Mock(stdout=json.dumps({'blockdevices':rows}))]):
            return disk.status()

    def test_actual_crypt_mapping_or_luks_backing_is_required(self):
        rows=[{'name':'/dev/mapper/root','type':'crypt','fstype':'ext4','children':[{'type':'part','fstype':'crypto_LUKS'}]}]
        self.assertEqual(self.check(rows),'encrypted')
        self.assertEqual(self.check([{'type':'crypt','fstype':'ext4'}]),'encrypted')
        self.assertEqual(self.check([{'name':'/dev/mapper/root','type':'lvm','fstype':'ext4','children':[{'type':'part','fstype':'LVM2_member'}]}]),'plain')
        self.assertEqual(self.check([{'name':'/dev/sda2','type':'part','fstype':'ext4'}]),'plain')

    def test_live_usb_does_not_claim_installed_disk_protection(self):
        with patch.object(disk.Path,'read_text',return_value='boot=live components'),patch.object(disk.subprocess,'run') as native:
            self.assertEqual(disk.status(),'live');native.assert_not_called()


if __name__=='__main__':unittest.main()
