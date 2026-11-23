"""Fresh fixture serial metadata migration, using temporary regular files only."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import settings_adjust_fixture_serials as serials
import settings_dualboot_vm as controller


class SerialTests(unittest.TestCase):
    def test_new_fixture_serials_fit_virtio_limit_and_remain_distinct(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(controller, 'run'):
            record = controller.create(argparse.Namespace(root=Path(tmp)/'fixture', disks='64,24', firmware='bios'))
        ids = [disk['serial'] for disk in record['disks']]
        self.assertEqual(ids, ['QA_SETTINGS_DISK_0', 'QA_SETTINGS_DISK_1'])
        self.assertEqual(len(set(ids)), 2)
        self.assertTrue(all(len(value.encode('ascii')) <= 20 for value in ids))

    def test_booted_or_active_fixture_is_rejected(self):
        for active, boots in [(True, []), (False, [{'number': 1}])]:
            with self.subTest(active=active, boots=boots):
                fixture = SimpleNamespace(active=lambda: active, record={'boots': boots})
                with self.assertRaisesRegex(RuntimeError, 'never-booted'):
                    serials.fresh(fixture)

    def test_only_matching_disk_metadata_is_adjusted(self):
        disk = {'file': 'disk-0.qcow2', 'gib': 96, 'serial': 'OWNED_SETTINGS_DISK_0'}
        value, changes = serials.adjusted({'disk': disk, 'hash': 'unchanged'}, [disk])
        self.assertEqual(value['disk']['serial'], 'QA_SETTINGS_DISK_0')
        self.assertEqual(value['hash'], 'unchanged')
        self.assertEqual(disk['serial'], 'OWNED_SETTINGS_DISK_0')
        self.assertEqual(len(changes), 1)
        with self.assertRaisesRegex(RuntimeError, 'Unrecognized'):
            serials.adjusted({'unrecognized_serial': 'OWNED_SETTINGS_DISK_0'}, [disk])

    def test_migration_retains_original_json_and_all_binary_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = base/'qa-node-first'; root.mkdir()
            disk = {'file': 'disk-0.qcow2', 'gib': 96, 'serial': 'OWNED_SETTINGS_DISK_0'}
            original = {'kind': 'settings-dualboot-vm-v1', 'firmware': 'bios', 'disks': [disk], 'boots': []}
            (root/'fixture.json').write_text(json.dumps(original))
            (root/'baseline.json').write_text(json.dumps({'disk': disk, 'sha256': 'a'*64}))
            old_fixture = (root/'fixture.json').read_bytes()
            for name in ('disk-0.qcow2', 'vars.fd', 'probe-usb.raw'):
                (root/name).write_bytes(('SYNTHETIC FIXTURE '+name).encode())
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in root.iterdir() if p.suffix != '.json'}
            result = serials.apply(serials.prepare(base, 'qa-node-first'))
            self.assertEqual(result['status'], 'completed')
            self.assertEqual((root/'serial-adjustment-originals/fixture.json').read_bytes(), old_fixture)
            self.assertEqual(json.loads((root/'fixture.json').read_text())['disks'][0]['serial'], 'QA_SETTINGS_DISK_0')
            for name, digest in before.items():
                self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), digest)
            evidence = json.loads((root/'serial-adjustment.json').read_text())
            self.assertEqual(evidence['status'], 'completed')
            self.assertEqual({x['name'] for x in evidence['changed_json']}, {'fixture.json', 'baseline.json'})


if __name__ == '__main__':
    unittest.main()
