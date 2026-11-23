#!/usr/bin/python3
"""Inspect only stopped, owned Settings QEMU fixture disks without mounting.

A checkpoint is a sparse regular raw file with a whole guest-visible SHA256,
CRC-checked primary/backup GPT and an EFI file inventory read through mtools.
Comparison checks the entire logical disk against that checkpoint, including
partition tables and unallocated sectors. No host block device is accepted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import stat
import struct
import subprocess
import sys
import time
import uuid
import zlib

from settings_dualboot_vm import Fixture, plain, require, run


SECTOR = 512
ESP_GUID = 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'
LABEL = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')


def owned_regular(path):
    path = plain(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(),
            'Only owned regular fixture files are accepted.')
    return path


def disk_info(fixture, index):
    require(not fixture.active(), 'Stop the owned QEMU fixture before disk inspection.')
    require(0 <= index < len(fixture.record['disks']), 'Invalid fixture disk index.')
    disk = fixture.record['disks'][index]
    image = owned_regular(fixture.root / disk['file'])
    require(image.parent == fixture.root, 'Disk must be directly inside this fixture.')
    info = json.loads(run(['qemu-img', 'info', '--output=json', '-f', 'qcow2', str(image)],
                          capture_output=True, text=True).stdout)
    require(info.get('format') == 'qcow2' and not info.get('backing-filename'),
            'A standalone owned qcow2 image is required.')
    require(info['virtual-size'] == disk['gib'] * 1024**3,
            'The disk size does not match its fixture declaration.')
    return disk, image, info


def read_exact(stream, offset, size):
    require(offset >= 0 and 0 <= size <= 16 * 1024**2, 'Invalid bounded disk read.')
    stream.seek(offset)
    data = stream.read(size)
    require(len(data) == size, 'The fixture image is truncated.')
    return data


def gpt(path):
    """Validate both GPT copies, their checksums and every partition extent."""
    size = path.stat().st_size
    require(size % SECTOR == 0, 'Disk size is not sector aligned.')
    sectors = size // SECTOR
    with path.open('rb') as disk:
        mbr = read_exact(disk, 0, SECTOR)
        require(mbr[510:512] == b'\x55\xaa' and any(mbr[450+i*16] == 0xEE for i in range(4)),
                'The fixture does not have a protective MBR.')

        def header(lba):
            raw = read_exact(disk, lba * SECTOR, SECTOR)
            require(raw[:8] == b'EFI PART', 'Missing GPT header.')
            version, length, checksum, reserved = struct.unpack_from('<4I', raw, 8)
            require(version == 0x10000 and 92 <= length <= SECTOR and reserved == 0,
                    'Unsupported GPT header.')
            check = bytearray(raw[:length]); check[16:20] = b'\0' * 4
            require(zlib.crc32(check) == checksum, 'GPT header checksum mismatch.')
            current, backup, first, last = struct.unpack_from('<4Q', raw, 24)
            entries_lba, count, entry_size, entries_crc = struct.unpack_from('<QIII', raw, 72)
            require(current == lba and backup < sectors and first <= last < sectors,
                    'GPT header lies outside the fixture disk.')
            require(1 <= count <= 4096 and 128 <= entry_size <= 4096 and entry_size % 8 == 0,
                    'Invalid GPT partition entry dimensions.')
            length = count * entry_size
            require(entries_lba >= 2 and entries_lba * SECTOR + length <= size,
                    'GPT partition entries lie outside the fixture disk.')
            entries = read_exact(disk, entries_lba * SECTOR, length)
            require(zlib.crc32(entries) == entries_crc, 'GPT partition table checksum mismatch.')
            return dict(current=current, backup=backup, first=first, last=last,
                        guid=str(uuid.UUID(bytes_le=raw[56:72])), count=count,
                        entry_size=entry_size, entries=entries, header_crc32=checksum,
                        entries_crc32=entries_crc)

        primary = header(1)
        require(primary['backup'] == sectors-1, 'Backup GPT must be at the final sector.')
        backup = header(primary['backup'])
        require(backup['backup'] == 1, 'Backup GPT does not point to the primary header.')
        for key in ('first', 'last', 'guid', 'count', 'entry_size', 'entries'):
            require(primary[key] == backup[key], 'Primary and backup GPT disagree: '+key)
        partitions = []
        for i in range(primary['count']):
            offset = i * primary['entry_size']
            entry = primary['entries'][offset:offset+primary['entry_size']]
            if not any(entry[:16]):
                continue
            start, end, flags = struct.unpack_from('<3Q', entry, 32)
            require(primary['first'] <= start <= end <= primary['last'],
                    'A GPT partition lies outside the usable disk.')
            name = entry[56:128].decode('utf-16le', errors='strict').split('\0', 1)[0]
            partitions.append(dict(number=i+1, start=start, sectors=end-start+1,
                                   bytes=(end-start+1)*SECTOR, name=name, flags=flags,
                                   type_guid=str(uuid.UUID(bytes_le=entry[:16])),
                                   partition_guid=str(uuid.UUID(bytes_le=entry[16:32]))))
        ordered = sorted(partitions, key=lambda p: p['start'])
        require(all(a['start']+a['sectors'] <= b['start'] for a, b in zip(ordered, ordered[1:])),
                'The fixture GPT partitions overlap.')
        return dict(sector_size=SECTOR, disk_guid=primary['guid'],
                    primary_header_crc32=primary['header_crc32'],
                    backup_header_crc32=backup['header_crc32'],
                    partition_entries_crc32=primary['entries_crc32'],
                    primary_backup_match=True, partitions=partitions)


def whole_sha(path):
    digest = hashlib.sha256()
    read = 0; heartbeat = time.monotonic()+20
    with path.open('rb') as source:
        while data := source.read(16 * 1024**2):
            digest.update(data); read += len(data)
            if time.monotonic() >= heartbeat:
                print(json.dumps({'hashing':path.name, 'logical_bytes_read':read}), file=sys.stderr, flush=True)
                heartbeat = time.monotonic()+20
    return digest.hexdigest()


def bounded_output(command, limit):
    """Keep both process time and potentially damaged filesystem output bounded."""
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    output = {process.stdout: bytearray(), process.stderr: bytearray()}
    deadline = time.monotonic()+45
    try:
        with selectors.DefaultSelector() as watch:
            for stream in output:
                watch.register(stream, selectors.EVENT_READ)
            while watch.get_map():
                require(time.monotonic() < deadline, 'EFI inspection timed out.')
                for ready, _ in watch.select(min(1, max(.01, deadline-time.monotonic()))):
                    chunk = os.read(ready.fileobj.fileno(), 65536)
                    if not chunk:
                        watch.unregister(ready.fileobj)
                        continue
                    output[ready.fileobj].extend(chunk)
                    maximum = limit if ready.fileobj is process.stdout else 16384
                    require(len(output[ready.fileobj]) <= maximum, 'EFI inspection output exceeds its bound.')
        code = process.wait(timeout=2)
        require(code == 0, 'EFI inspection failed: '+output[process.stderr].decode(errors='replace'))
        return bytes(output[process.stdout])
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)
        process.stdout.close(); process.stderr.close()


def efi_inventory(path, table):
    """Use read-only mdir/mtype; never extract or mount a guest filesystem."""
    require(shutil.which('mdir') and shutil.which('mtype'), 'Read-only mtools inspection is unavailable.')
    inventories = []
    for part in table['partitions']:
        if part['type_guid'] != ESP_GUID:
            continue
        image = str(path)+'@@'+str(part['start']*SECTOR)
        listing = bounded_output(['mdir', '-i', image, '-/', '-b', '::/EFI'], 1024**2).decode('utf-8', errors='strict')
        paths = [value for value in map(str.strip, listing.splitlines()) if value and not value.endswith('/')]
        require(len(paths) <= 256, 'Unexpectedly large EFI fixture directory.')
        files = []
        for name in sorted(paths):
            require(name.startswith('::/EFI/') and len(name) <= 512
                    and all(piece not in ('', '.', '..') for piece in name[3:].split('/'))
                    and not any(ord(c) < 32 for c in name), 'Invalid EFI filename in fixture.')
            contents = bounded_output(['mtype', '-i', image, name], 32 * 1024**2)
            record = dict(path=name[2:], bytes=len(contents),
                          sha256=hashlib.sha256(contents).hexdigest())
            if name.lower().endswith('.cfg') and len(contents) <= 128*1024:
                record['text'] = contents.decode('utf-8', errors='replace')
            files.append(record)
        inventories.append(dict(partition=part['number'], files=files))
    require(inventories, 'No EFI System Partition was found in the installed fixture.')
    require(any(p['files'] for p in inventories), 'The fixture EFI System Partition has no boot files.')
    return inventories


def checkpoint(fixture, index, label):
    require(LABEL.fullmatch(label), 'Invalid checkpoint label.')
    disk, image, info = disk_info(fixture, index)
    target = plain(fixture.root / f'checkpoint-{label}-disk{index}.raw')
    report = plain(target.with_suffix('.json'))
    require(not target.exists() and not report.exists(), 'Use a new checkpoint label.')
    estimate = image.stat().st_blocks * 512 + 512 * 1024**2
    require(shutil.disk_usage(fixture.root).free >= estimate, 'Insufficient free space for a sparse checkpoint.')
    run(['qemu-img', 'convert', '-f', 'qcow2', '-O', 'raw', '-S', '4k', str(image), str(target)], timeout=600)
    owned_regular(target)
    require(target.stat().st_size == info['virtual-size'], 'Checkpoint virtual size mismatch.')
    table = gpt(target)
    efi = efi_inventory(target, table)
    result = dict(kind='settings-disk-checkpoint-v1', disk_index=index, disk=disk,
                  raw=target.name, virtual_bytes=target.stat().st_size,
                  allocated_bytes=target.stat().st_blocks*512, sha256=whole_sha(target),
                  gpt=table, efi=efi, created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    report.write_text(json.dumps(result, indent=2)+'\n')
    return result


def compare(fixture, index, checkpoint_name, label):
    require(LABEL.fullmatch(label), 'Invalid comparison label.')
    disk, image, info = disk_info(fixture, index)
    report_path = owned_regular(fixture.root / checkpoint_name)
    require(report_path.parent == fixture.root and report_path.suffix == '.json', 'Checkpoint must belong to this fixture.')
    require(report_path.stat().st_size <= 1024**2, 'Checkpoint report is too large.')
    baseline = json.loads(report_path.read_text())
    require(baseline.get('kind') == 'settings-disk-checkpoint-v1' and baseline['disk_index'] == index
            and baseline['disk'] == disk, 'Checkpoint belongs to a different fixture disk.')
    raw = owned_regular(fixture.root / baseline['raw'])
    require(raw.parent == fixture.root and raw.stat().st_size == info['virtual-size'] == baseline['virtual_bytes'],
            'Checkpoint disk size changed.')
    require(whole_sha(raw) == baseline['sha256'], 'The retained checkpoint bytes changed.')
    output = plain(fixture.root / f'comparison-{label}-disk{index}.json')
    require(not output.exists(), 'Use a new comparison label.')
    command = ['qemu-img', 'compare', '-f', 'raw', '-F', 'qcow2', str(raw), str(image)]
    value = subprocess.run(command, capture_output=True, text=True, timeout=600)
    result = dict(kind='settings-disk-comparison-v1', equal=value.returncode == 0,
                  logical_bytes=info['virtual-size'], baseline_sha256=baseline['sha256'],
                  checkpoint=report_path.name, disk=disk, command=command,
                  exit_code=value.returncode, stdout=value.stdout, stderr=value.stderr,
                  scope='Every guest-visible byte, including GPT, EFI, filesystems and unallocated sectors')
    output.write_text(json.dumps(result, indent=2)+'\n')
    require(value.returncode == 0, 'The other fixture disk changed; see '+str(output))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('checkpoint', 'compare'))
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--disk', required=True, type=int)
    parser.add_argument('--label', required=True)
    parser.add_argument('--checkpoint')
    args = parser.parse_args()
    fixture = Fixture(args.root)
    if args.action == 'checkpoint':
        result = checkpoint(fixture, args.disk, args.label)
    else:
        require(args.checkpoint, 'Please name the retained checkpoint report.')
        result = compare(fixture, args.disk, args.checkpoint, args.label)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
