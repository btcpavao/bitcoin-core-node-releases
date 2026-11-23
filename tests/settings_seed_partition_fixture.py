#!/usr/bin/python3
"""Seed or inspect owned, stopped UEFI QA files without mounting filesystems.

The seeded foreign EFI files are synthetic preservation sentinels, not a third
operating system or a bootable fallback. This helper never starts a VM.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import time
import uuid

from settings_dualboot_vm import Fixture, create, plain, require, run
from settings_disk_readback import (ESP_GUID, checkpoint, disk_info,
                                    efi_inventory, gpt, owned_regular)


MIB = 1024**2
GIB = 1024**3
DISK_BYTES = 96 * GIB
ESP_START = 2048
ESP_SECTORS = 512 * MIB // 512
DATA_START = ESP_START + ESP_SECTORS
DATA_SECTORS = GIB // 512
BASELINE = 'seed-preservation-baseline.json'
PART_KEYS = ('number', 'start', 'sectors', 'bytes', 'name', 'flags',
             'type_guid', 'partition_guid')


def span_sha(path, offset, size):
    path = owned_regular(path)
    require(offset >= 0 and size > 0 and offset+size <= path.stat().st_size,
            'Hash span is outside the owned image.')
    digest = hashlib.sha256()
    with path.open('rb') as source:
        source.seek(offset)
        remaining = size
        while remaining:
            chunk = source.read(min(4 * MIB, remaining))
            require(chunk, 'Truncated hash span.')
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def part_record(part):
    return {key: part[key] for key in PART_KEYS}


def fat_identity(raw, part):
    with owned_regular(raw).open('rb') as source:
        source.seek(part['start'] * 512)
        sector = source.read(512)
    require(len(sector) == 512 and sector[510:] == b'\x55\xaa'
            and sector[82:90] == b'FAT32   ', 'Expected the seeded FAT32 ESP.')
    return {'volume_id': f'{struct.unpack_from("<I", sector, 67)[0]:08X}',
            'label': sector[71:82].decode('ascii').rstrip(),
            'filesystem': 'FAT32'}


def embed_sparse(source, target, offset):
    source, target = owned_regular(source), owned_regular(target)
    require(offset >= MIB and offset+source.stat().st_size < target.stat().st_size-MIB,
            'Embedding may not overlap GPT metadata.')
    zero = bytes(4 * MIB)
    with source.open('rb') as src, target.open('r+b') as dst:
        dst.seek(offset)
        while chunk := src.read(len(zero)):
            if chunk == zero[:len(chunk)]:
                dst.seek(len(chunk), 1)
            else:
                dst.write(chunk)


def seed(root, first_product='node'):
    require(first_product in ('node', 'vault'), 'The first product must be explicit.')
    root = plain(root)
    require(re.fullmatch(r'[A-Za-z0-9/_-]+', str(root)),
            'Use a simple fixture path for debugfs command parsing.')
    create(argparse.Namespace(root=root, disks='96', firmware='uefi'))
    fixture = Fixture(root)
    require(not fixture.active() and not fixture.record['boots'], 'Only a fresh fixture may be seeded.')
    token = str(uuid.uuid4())
    raw, esp, data = (root/name for name in ('seed-disk.raw', 'seed-esp.raw', 'seed-data.raw'))
    for path, size in ((raw, DISK_BYTES), (esp, 512*MIB), (data, GIB)):
        with path.open('xb') as handle:
            handle.truncate(size)
    layout = (f'label: gpt\nstart={ESP_START},size={ESP_SECTORS},type=U,name=QA_ESP\n'
              f'start={DATA_START},size={DATA_SECTORS},type=L,name=QA_KEEP_DATA\n')
    run(['/usr/sbin/sfdisk', str(raw)], input=layout, text=True, capture_output=True)
    table = gpt(raw)
    require(len(table['partitions']) == 2, 'Unexpected seeded partition count.')
    run(['/usr/sbin/mkfs.fat', '-F', '32', '-n', 'QA_ESP', str(esp)], capture_output=True)
    run(['/usr/sbin/mkfs.ext4', '-F', '-q', '-L', 'QA_KEEP_DATA', '-U', str(uuid.uuid4()),
         '-m', '0', '-E', 'lazy_itable_init=0,lazy_journal_init=0', str(data)], capture_output=True)
    fallback = root/'foreign-fallback-sentinel.txt'
    unrelated = root/'unrelated-efi-sentinel.txt'
    sentinel = root/'existing-data-sentinel.txt'
    fallback.write_text('SYNTHETIC FOREIGN FALLBACK; NOT AN EFI PROGRAM\nFixture: '+token+'\n')
    unrelated.write_text('SYNTHETIC UNRELATED EFI FILE; PRESERVE EXACT BYTES\nFixture: '+token+'\n')
    sentinel.write_text('SYNTHETIC EXISTING DATA PARTITION; PRESERVE THE ENTIRE PARTITION\nFixture: '+token+'\n')
    run(['mmd', '-i', str(esp), '::/EFI', '::/EFI/BOOT', '::/EFI/QA_FOREIGN'], capture_output=True)
    run(['mcopy', '-i', str(esp), str(fallback), '::/EFI/BOOT/BOOTX64.EFI'], capture_output=True)
    run(['mcopy', '-i', str(esp), str(unrelated), '::/EFI/QA_FOREIGN/SENTINEL.EFI'], capture_output=True)
    run(['/usr/sbin/debugfs', '-w', '-R', f'write {sentinel} /sentinel.txt', str(data)], capture_output=True)
    actual = run(['/usr/sbin/debugfs', '-R', 'cat /sentinel.txt', str(data)], capture_output=True).stdout
    require(actual == sentinel.read_bytes(), 'The synthetic ext4 sentinel did not read back.')
    data_sha = span_sha(data, 0, GIB)
    embed_sparse(esp, raw, ESP_START*512)
    embed_sparse(data, raw, DATA_START*512)
    require(span_sha(raw, DATA_START*512, GIB) == data_sha, 'Embedded data differs.')
    require(gpt(raw) == table, 'Seeding changed GPT metadata.')
    seeded_qcow = root/'seeded-disk-0.qcow2'
    run(['qemu-img', 'convert', '-f', 'raw', '-O', 'qcow2', '-S', '4k',
         str(raw), str(seeded_qcow)], timeout=300)
    _, target, info = disk_info(fixture, 0)
    require(info['virtual-size'] == DISK_BYTES and not fixture.record['boots'],
            'Refuse to replace a used fixture disk.')
    os.replace(seeded_qcow, target)
    snapshot = checkpoint(fixture, 0, 'pre-'+first_product)
    inspected = owned_regular(root/snapshot['raw'])
    require(snapshot['gpt'] == table, 'QCOW2 readback changed GPT metadata.')
    require(span_sha(inspected, DATA_START*512, GIB) == data_sha,
            'QCOW2 readback changed the existing data partition.')
    files = {item['path']: item for part in snapshot['efi'] for item in part['files']}
    for name, source in [('/EFI/BOOT/BOOTX64.EFI', fallback),
                         ('/EFI/QA_FOREIGN/SENTINEL.EFI', unrelated)]:
        require(files[name]['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest(),
                'QCOW2 readback changed a synthetic EFI sentinel.')
    baseline = dict(kind='settings-existing-partitions-baseline-v1', fixture=token,
                    disk=fixture.record['disks'][0], disk_guid=table['disk_guid'],
                    virtual_bytes=DISK_BYTES, checkpoint=f'checkpoint-pre-{first_product}-disk0.json',
                    first_product=first_product,
                    existing_partitions=[part_record(p) for p in table['partitions']],
                    data_partition_sha256=data_sha, data_sentinel_sha256=hashlib.sha256(actual).hexdigest(),
                    esp_identity=fat_identity(inspected, table['partitions'][0]),
                    preserved_efi_files=list(files.values()),
                    unallocated_start_sector=DATA_START+DATA_SECTORS,
                    unallocated_end_sector=DISK_BYTES//512-34,
                    booted=False, fallback_is_bootable=False)
    (root/BASELINE).write_text(json.dumps(baseline, indent=2)+'\n')
    (root/'README-QA.txt').write_text(
        'OWNED SYNTHETIC UEFI INSTALLATION FIXTURE\n'
        '96 GiB sparse QCOW2. Existing p1: 512 MiB FAT32 ESP. Existing p2: 1 GiB ext4 data.\n'
        'Remaining space is genuinely unallocated. The VM has never been booted.\n'
        'The two EFI sentinel files are NOT EFI programs or an installed third OS.\n'
        'BOOTX64.EFI deliberately simulates foreign/unowned fallback ownership.\n'
        'Boot installed products using their distinct UEFI NVRAM entries.\n'
        'Never attach a host disk or mount a guest filesystem for this QA.\n'
        'Readback baseline: '+BASELINE+'\n'
        'Before/after checks: stop the VM; run this helper verify with a fresh --label.\n')
    for temporary in (raw, esp, data):
        owned_regular(temporary).unlink()
    return dict(status='seeded-and-read-back', fixture=str(root), baseline=BASELINE,
                existing_esp_mib=512, existing_data_gib=1,
                genuinely_unallocated_gib=(baseline['unallocated_end_sector']-baseline['unallocated_start_sector']+1)*512/GIB,
                baseline_checkpoint_sha256=snapshot['sha256'], booted=False)


def verify(root, label):
    require(re.fullmatch(r'[A-Za-z0-9_-]{1,48}', label), 'Use a new simple verification label.')
    fixture = Fixture(root)
    disk, image, info = disk_info(fixture, 0)
    baseline_file = owned_regular(fixture.root/BASELINE)
    require(baseline_file.stat().st_size <= MIB, 'Unexpectedly large QA baseline.')
    baseline = json.loads(baseline_file.read_text())
    require(baseline.get('kind') == 'settings-existing-partitions-baseline-v1'
            and baseline['disk'] == disk and baseline['virtual_bytes'] == info['virtual-size'],
            'Baseline belongs to a different fixture.')
    raw = plain(fixture.root/f'preservation-{label}.raw')
    report = plain(raw.with_suffix('.json'))
    require(not raw.exists() and not report.exists(), 'Use a new verification label.')
    run(['qemu-img', 'convert', '-f', 'qcow2', '-O', 'raw', '-S', '4k',
         str(image), str(raw)], timeout=600)
    owned_regular(raw)
    table = gpt(raw)
    require(table['disk_guid'] == baseline['disk_guid'], 'Existing disk GPT identity changed.')
    by_number = {p['number']: p for p in table['partitions']}
    for expected in baseline['existing_partitions']:
        require(expected['number'] in by_number
                and part_record(by_number[expected['number']]) == expected,
                'Existing partition identity, boundaries, name or flags changed.')
    data = by_number[2]
    actual_data = span_sha(raw, data['start']*512, data['bytes'])
    require(actual_data == baseline['data_partition_sha256'], 'Existing data partition bytes changed.')
    esp = by_number[1]
    require(esp['type_guid'] == ESP_GUID and fat_identity(raw, esp) == baseline['esp_identity'],
            'Existing FAT32 ESP identity changed.')
    inventory = efi_inventory(raw, table)
    files = {item['path']: item for part in inventory if part['partition'] == 1 for item in part['files']}
    for expected in baseline['preserved_efi_files']:
        require(files.get(expected['path']) == expected, 'Existing foreign EFI bytes changed: '+expected['path'])
    result = dict(kind='settings-existing-partitions-preservation-v1', status='passed',
                  label=label, data_partition_sha256=actual_data,
                  preserved_efi_files=baseline['preserved_efi_files'],
                  gpt=table, efi=inventory, inspected_raw=raw.name,
                  created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    report.write_text(json.dumps(result, indent=2)+'\n')
    return dict(status='passed', report=str(report),
                checks=['existing GPT disk and partition identities', 'entire existing data partition',
                        'existing FAT32 ESP identity', 'foreign fallback and unrelated EFI file bytes'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['seed', 'verify'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--first-product', choices=['node', 'vault'], default='node')
    parser.add_argument('--label')
    args = parser.parse_args()
    require(args.action == 'seed' or args.label, 'Verification requires a fresh --label.')
    result = seed(args.root, args.first_product) if args.action == 'seed' else verify(args.root, args.label)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
