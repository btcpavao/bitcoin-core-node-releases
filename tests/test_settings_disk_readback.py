"""Bounds and corruption checks for mount-free acceptance evidence."""
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid
import zlib

import settings_disk_readback as readback


def synthetic_gpt(path, overlap=False):
    sectors = 8192
    table = bytearray(128*128)
    for index, (start, end) in enumerate([(2048, 4095), (3000 if overlap else 4096, 6000)]):
        offset = index*128
        table[offset:offset+16] = uuid.UUID(readback.ESP_GUID).bytes_le
        table[offset+16:offset+32] = uuid.uuid4().bytes_le
        struct.pack_into('<3Q', table, offset+32, start, end, 0)
        name = ('Partition '+str(index)).encode('utf-16le')
        table[offset+56:offset+56+len(name)] = name
    guid = uuid.uuid4().bytes_le
    with path.open('wb') as image:
        image.truncate(sectors*512)
        mbr = bytearray(512); mbr[450] = 0xEE; mbr[510:512] = b'\x55\xaa'
        image.seek(0); image.write(mbr)
        for current, other, entries in [(1, sectors-1, 2), (sectors-1, 1, sectors-33)]:
            header = bytearray(512); header[:8] = b'EFI PART'
            struct.pack_into('<4I4Q', header, 8, 0x10000, 92, 0, 0, current, other, 34, sectors-34)
            header[56:72] = guid
            struct.pack_into('<QIII', header, 72, entries, 128, 128, zlib.crc32(table))
            struct.pack_into('<I', header, 16, zlib.crc32(header[:92]))
            image.seek(current*512); image.write(header)
            image.seek(entries*512); image.write(table)


class ReadbackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.image = self.root/'image.raw'
        synthetic_gpt(self.image)

    def tearDown(self):
        self.temporary.cleanup()

    def test_both_gpt_copies_and_partition_extents_are_reported(self):
        value = readback.gpt(self.image)
        self.assertTrue(value['primary_backup_match'])
        self.assertEqual(value['partitions'][0]['name'], 'Partition 0')
        self.assertEqual(value['partitions'][0]['bytes'], 1024**2)

    def test_primary_header_corruption_is_rejected(self):
        with self.image.open('r+b') as stream:
            stream.seek(512+56); stream.write(b'\xff'*16)
        with self.assertRaisesRegex(RuntimeError, 'header checksum'):
            readback.gpt(self.image)

    def test_backup_table_corruption_is_rejected(self):
        with self.image.open('r+b') as stream:
            stream.seek((8192-33)*512+32); stream.write(b'\xff')
        with self.assertRaisesRegex(RuntimeError, 'table checksum'):
            readback.gpt(self.image)

    def test_overlapping_partitions_are_rejected_even_with_valid_checksums(self):
        synthetic_gpt(self.image, overlap=True)
        with self.assertRaisesRegex(RuntimeError, 'overlap'):
            readback.gpt(self.image)

    def test_symlinked_files_and_parent_directories_are_rejected(self):
        link = self.root/'link.raw'; link.symlink_to(self.image)
        with self.assertRaisesRegex(RuntimeError, 'Symlinked'):
            readback.owned_regular(link)
        directory = self.root/'alias'; directory.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'Symlinked'):
            readback.owned_regular(directory/'image.raw')

    def test_running_fixture_is_rejected_before_image_access(self):
        class Active:
            def active(self):
                return True
        with self.assertRaisesRegex(RuntimeError, 'Stop the owned'):
            readback.disk_info(Active(), 0)

    def test_checkpoint_rejects_dangling_output_symlink_before_writer(self):
        fixture = SimpleNamespace(root=self.root)
        info = ({}, self.image, {'virtual-size': self.image.stat().st_size})
        for suffix in ('raw', 'json'):
            with self.subTest(suffix=suffix):
                label = 'dangling-'+suffix
                output = self.root/f'checkpoint-{label}-disk0.{suffix}'
                outside = self.root/f'missing-{suffix}'
                output.symlink_to(outside)
                with mock.patch.object(readback, 'disk_info', return_value=info), \
                     mock.patch.object(readback, 'run') as writer:
                    with self.assertRaisesRegex(RuntimeError, 'Symlinked'):
                        readback.checkpoint(fixture, 0, label)
                    writer.assert_not_called()
                self.assertFalse(outside.exists())

    def test_process_output_is_bounded_and_binary_preserved(self):
        value = readback.bounded_output([sys.executable, '-c', 'import sys;sys.stdout.buffer.write(bytes(range(256)))'], 256)
        self.assertEqual(value, bytes(range(256)))
        with self.assertRaisesRegex(RuntimeError, 'exceeds its bound'):
            readback.bounded_output([sys.executable, '-c', 'import sys;sys.stdout.buffer.write(b"x"*1000000)'], 1024)


if __name__ == '__main__':
    unittest.main()
