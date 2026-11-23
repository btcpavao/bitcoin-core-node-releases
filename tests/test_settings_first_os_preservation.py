"""First-OS evidence regressions: synthetic regular files and mocked probes only."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import settings_first_os_preservation as first


class FirstOsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = SimpleNamespace(root=self.root, record={'firmware': 'uefi'}, active=lambda: False)
        self.disk = {'file': 'disk-0.qcow2', 'gib': 96, 'serial': 'QA_SETTINGS_DISK_0'}
        self.esp = dict(number=1, start=1, sectors=8, bytes=4096, name='QA_ESP', flags=0,
                        type_guid=first.ESP_GUID, partition_guid='aaaaaaaa-0000-0000-0000-000000000001')
        self.partition = dict(number=3, start=16, sectors=8, bytes=4096, name='BitcoinCoreNode', flags=0,
                              type_guid='0fc63daf-8483-4772-8e79-3d69d8477de4',
                              partition_guid='aaaaaaaa-0000-0000-0000-000000000003')
        self.table = dict(disk_guid='bbbbbbbb-0000-0000-0000-000000000000',
                          partitions=[self.esp, self.partition])
        self.metadata = dict(schema=1, product='node', boot_id='BitcoinCoreNode',
                             disk_guid=self.table['disk_guid'], root_partuuid=self.partition['partition_guid'],
                             root_fsuuid='root-fs', esp_partuuid=self.esp['partition_guid'],
                             esp_fsuuid='1234-ABCD', serial=self.disk['serial'])
        self.files = [{'path': '/EFI/BitcoinCoreNode/grubx64.efi', 'bytes': 2048, 'sha256': 'a'*64},
                      {'path': '/EFI/BitcoinCoreNode/grub.cfg', 'bytes': 48, 'sha256': 'b'*64}]
        self.before = self.snapshot('first')
        self.after = self.snapshot('second')
        self.current = self.before
        self.patches = [
            mock.patch.object(first, 'MIN_ROOT', {'node': 4096, 'vault': 4096}),
            mock.patch.object(first, 'load_snapshot', side_effect=lambda fixture, name: self.current),
            mock.patch.object(first, 'filesystem', side_effect=lambda raw, part:
                              {'type': 'vfat', 'uuid': '1234-ABCD'} if part['number'] == 1
                              else {'type': 'ext4', 'uuid': 'root-fs'}),
            mock.patch.object(first, 'efi_inventory', side_effect=lambda raw, table: self.current['report']['efi']),
            mock.patch.object(first, 'bounded_output', side_effect=lambda *args: json.dumps(self.metadata).encode()),
            mock.patch.object(first, 'fat_identity', return_value={'volume_id': '1234ABCD', 'label': 'QA_ESP', 'filesystem': 'FAT32'}),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temporary.cleanup()

    def snapshot(self, label):
        raw = self.root/f'preservation-{label}.raw'
        raw.write_bytes(bytes(range(256))*64)
        report = dict(kind='settings-existing-partitions-preservation-v1', status='passed',
                      inspected_raw=raw.name, gpt=deepcopy(self.table),
                      efi=[{'partition': 1, 'files': deepcopy(self.files)}])
        path = raw.with_suffix('.json')
        path.write_text(json.dumps(report))
        return dict(fixture=self.fixture, disk=self.disk, raw=raw, raw_stamp=first.stamp(raw),
                    report=report, report_path=path, report_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    table=deepcopy(self.table), seed_fixture='synthetic-fixture')

    def capture(self):
        self.current = self.before
        return first.capture(self.fixture, self.before['report_path'].name, 'node', 3)

    def compare(self, label='after-second'):
        self.current = self.after
        return first.compare(self.fixture, self.after['report_path'].name, 'node', 3, label)

    def test_equal_root_and_vendor_files_allow_peer_efi_additions(self):
        captured = self.capture()
        self.assertEqual(captured['root_bytes'], 4096)
        self.after['report']['efi'][0]['files'].append(
            {'path': '/EFI/BitcoinCoreVault/grubx64.efi', 'bytes': 2048, 'sha256': 'c'*64})
        result = self.compare()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['root_sha256'], captured['root_sha256'])

    def test_one_changed_root_byte_is_detected(self):
        self.capture()
        with self.after['raw'].open('r+b') as stream:
            stream.seek(self.partition['start']*512+37); stream.write(b'\xff')
        self.after['raw_stamp'] = first.stamp(self.after['raw'])
        with self.assertRaisesRegex(RuntimeError, 'root_sha256'):
            self.compare()
        record = json.loads((self.root/'first-os-node-p3-after-second.json').read_text())
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(record['differences'], ['root_sha256'])

    def test_changed_removed_or_added_original_vendor_file_is_detected(self):
        self.capture()
        original = deepcopy(self.after['report']['efi'][0]['files'])
        for action in ('changed', 'removed', 'added'):
            with self.subTest(action=action):
                files = deepcopy(original)
                if action == 'changed':
                    files[1]['sha256'] = 'f'*64
                elif action == 'removed':
                    files.pop()
                else:
                    files.append({'path': '/EFI/BitcoinCoreNode/unexpected.cfg', 'bytes': 1, 'sha256': 'd'*64})
                self.after['report']['efi'][0]['files'] = files
                with self.assertRaisesRegex(RuntimeError, 'vendor_files'):
                    self.compare(action)

    def test_wrong_product_or_root_identity_rejected_before_root_hash(self):
        for field, value in [('product', 'vault'), ('root_partuuid', self.esp['partition_guid']),
                             ('root_fsuuid', 'different'), ('serial', 'OTHER_DISK')]:
            with self.subTest(field=field):
                prior = self.metadata[field]; self.metadata[field] = value
                with mock.patch.object(first, 'root_sha') as hasher:
                    with self.assertRaisesRegex(RuntimeError, 'does not bind'):
                        self.capture()
                    hasher.assert_not_called()
                self.metadata[field] = prior

    def test_selected_esp_or_missing_partition_cannot_be_used_as_root(self):
        for number in (1, 2, 4):
            with self.subTest(number=number), mock.patch.object(first, 'root_sha') as hasher:
                with self.assertRaises(RuntimeError):
                    first.capture(self.fixture, self.before['report_path'].name, 'node', number)
                hasher.assert_not_called()

    def test_reusing_original_readback_is_rejected(self):
        self.capture()
        self.after = self.before
        with self.assertRaisesRegex(RuntimeError, 'second installation readback'):
            self.compare()

    def test_changed_original_report_or_resized_raw_is_rejected(self):
        self.capture()
        original = self.before['report_path'].read_bytes()
        self.before['report_path'].write_bytes(original+b'\n')
        with self.assertRaisesRegex(RuntimeError, 'readback report changed'):
            self.compare('report')
        self.before['report_path'].write_bytes(original)
        with self.before['raw'].open('r+b') as stream:
            stream.truncate(self.before['raw'].stat().st_size-512)
        with self.assertRaisesRegex(RuntimeError, 'raw metadata changed'):
            self.compare('raw')

    def test_dangling_output_symlink_is_rejected_before_inspection(self):
        output = self.root/'first-os-node-p3.json'
        output.symlink_to(self.root/'outside.json')
        with mock.patch.object(first, 'inspect') as inspector:
            with self.assertRaisesRegex(RuntimeError, 'Symlinked'):
                self.capture()
            inspector.assert_not_called()
        self.assertFalse((self.root/'outside.json').exists())

    def test_duplicate_or_oversized_metadata_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Duplicate'):
            first.decode_json(b'{"schema":1,"schema":true}')
        with self.assertRaisesRegex(RuntimeError, 'size bound'):
            first.decode_json(b' '*65537, 65536)


class SnapshotTests(unittest.TestCase):
    def test_live_fixture_is_rejected_before_raw_access(self):
        fixture = SimpleNamespace(active=lambda: True)
        with self.assertRaisesRegex(RuntimeError, 'Stop the owned'):
            first.load_snapshot(fixture, 'preservation-after-node.json')

    def test_external_paths_and_symlinked_raw_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture = SimpleNamespace(root=root)
            for name in ('../preservation-x.raw', '/tmp/preservation-x.raw'):
                with self.assertRaisesRegex(RuntimeError, 'filename'):
                    first.member(fixture, name, first.RAW_NAME)
            (root/'preservation-x.raw').symlink_to(root/'missing')
            with self.assertRaisesRegex(RuntimeError, 'Symlinked'):
                first.member(fixture, 'preservation-x.raw', first.RAW_NAME)


if __name__ == '__main__':
    unittest.main()
