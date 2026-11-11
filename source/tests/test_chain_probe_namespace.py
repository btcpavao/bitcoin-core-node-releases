"""Current net namespace, independent of the inherited sysfs mount."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import chain_probe


class ProbeNamespace(unittest.TestCase):
    def test_private_loopback_namespace_is_accepted_without_sysfs_visibility(self):
        own=types.SimpleNamespace(st_dev=4,st_ino=10)
        parent=types.SimpleNamespace(st_dev=4,st_ino=11)
        with patch.object(chain_probe.os,'stat',side_effect=[own,parent]),patch.object(chain_probe.socket,'if_nameindex',return_value=[(1,'lo')]):
            chain_probe.verify_private_network()

    def test_original_or_connected_namespace_is_rejected(self):
        own=types.SimpleNamespace(st_dev=4,st_ino=10)
        parent=types.SimpleNamespace(st_dev=4,st_ino=11)
        for records,interfaces in (([own,own],[(1,'lo')]),([own,parent],[(1,'lo'),(2,'eth0')]),([own,parent],[])):
            with self.subTest(interfaces=interfaces),patch.object(chain_probe.os,'stat',side_effect=records),patch.object(chain_probe.socket,'if_nameindex',return_value=interfaces):
                with self.assertRaises(RuntimeError):chain_probe.verify_private_network()


if __name__=='__main__':unittest.main()
