#!/usr/bin/python3
"""Compare first-OS root bytes and product EFI files in retained QA readbacks.

Reads existing preservation-*.raw/.json only. Never converts an image, starts
a VM, mounts a filesystem, or hashes the unselected part of a fixture disk.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from settings_dualboot_vm import Fixture, plain, require
from settings_disk_readback import (ESP_GUID, bounded_output, disk_info,
                                    efi_inventory, gpt, owned_regular)
from settings_seed_partition_fixture import BASELINE, fat_identity, part_record


GIB = 1024**3
PRODUCTS = {'node': 'BitcoinCoreNode', 'vault': 'BitcoinCoreVault'}
MIN_ROOT = {'node': 32*GIB, 'vault': 16*GIB}
REPORT_NAME = re.compile(r'preservation-[A-Za-z0-9_-]{1,48}\.json\Z')
RAW_NAME = re.compile(r'preservation-[A-Za-z0-9_-]{1,48}\.raw\Z')


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'Duplicate key in QA evidence.')
        value[key] = item
    return value


def decode_json(data, limit=1024**2):
    require(len(data) <= limit, 'QA evidence exceeds its size bound.')
    value = json.loads(data, object_pairs_hook=unique_object)
    require(isinstance(value, dict), 'QA evidence must be an object.')
    return value


def read_json(path):
    path = owned_regular(path)
    require(path.stat().st_size <= 1024**2, 'QA evidence exceeds its size bound.')
    data = path.read_bytes()
    return decode_json(data), hashlib.sha256(data).hexdigest()


def member(fixture, name, pattern):
    require(isinstance(name, str) and pattern.fullmatch(name), 'Use a fixture evidence filename, not an external path.')
    path = plain(fixture.root/name)
    require(path.parent == fixture.root, 'Evidence must belong to this fixture.')
    return path


def stamp(path):
    info = owned_regular(path).stat()
    return {name: getattr(info, name) for name in
            ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}


def load_snapshot(fixture, report_name):
    disk, _, info = disk_info(fixture, 0)
    require(fixture.record['firmware'] == 'uefi', 'First-OS peer preservation requires the UEFI fixture.')
    report_path = member(fixture, report_name, REPORT_NAME)
    report, report_sha = read_json(report_path)
    require(report.get('kind') == 'settings-existing-partitions-preservation-v1'
            and report.get('status') == 'passed', 'Use a successful existing preservation readback.')
    raw = member(fixture, report.get('inspected_raw'), RAW_NAME)
    require(raw.stem == report_path.stem, 'Readback report and raw image names differ.')
    initial_stamp = stamp(raw)
    require(initial_stamp['st_size'] == info['virtual-size'], 'Raw readback size does not match the fixture.')
    table = gpt(raw)
    require(table == report.get('gpt'), 'Raw GPT no longer matches its readback report.')
    seed, _ = read_json(fixture.root/BASELINE)
    require(seed.get('kind') == 'settings-existing-partitions-baseline-v1'
            and seed.get('disk') == disk and seed.get('virtual_bytes') == info['virtual-size']
            and seed.get('disk_guid') == table['disk_guid'], 'Readback belongs to a different seeded fixture.')
    return dict(fixture=fixture, disk=disk, raw=raw, raw_stamp=initial_stamp,
                report=report, report_path=report_path, report_sha256=report_sha,
                table=table, seed_fixture=seed['fixture'])


def filesystem(raw, part):
    output = bounded_output(['/usr/sbin/blkid', '-p', '-o', 'export',
                             '-O', str(part['start']*512), '-S', str(part['bytes']),
                             str(raw)], 64*1024).decode('utf-8', errors='strict')
    values = {}
    for line in output.splitlines():
        require('=' in line, 'Malformed fixture filesystem probe.')
        key, value = line.split('=', 1)
        require(key not in values, 'Duplicate filesystem probe field.')
        values[key] = value
    require(values.get('TYPE') and values.get('UUID'), 'Filesystem type or identity is missing.')
    return {'type': values['TYPE'], 'uuid': values['UUID']}


def root_sha(raw, part):
    offset, remaining = part['start']*512, part['bytes']
    require(offset >= 0 and remaining > 0 and offset+remaining <= raw.stat().st_size,
            'Selected root span is outside the owned raw readback.')
    digest = hashlib.sha256(); read = 0; heartbeat = time.monotonic()+20
    with raw.open('rb') as source:
        source.seek(offset)
        while remaining:
            chunk = source.read(min(16*1024**2, remaining))
            require(chunk, 'Truncated selected root span.')
            digest.update(chunk); read += len(chunk); remaining -= len(chunk)
            if time.monotonic() >= heartbeat:
                print(json.dumps({'hashing_root': part['number'], 'bytes_read': read,
                                  'root_bytes': part['bytes']}), file=sys.stderr, flush=True)
                heartbeat = time.monotonic()+20
    return digest.hexdigest()


def inspect(snapshot, product, number):
    require(product in PRODUCTS and type(number) is int and 1 <= number <= 4096,
            'Supply an explicit product and observed GPT partition number.')
    table, raw = snapshot['table'], snapshot['raw']
    choices = [p for p in table['partitions'] if p['number'] == number]
    require(len(choices) == 1, 'The selected root partition is missing or duplicated.')
    root = choices[0]
    require(root['type_guid'] != ESP_GUID and root['bytes'] >= MIN_ROOT[product],
            'The selected partition is not a sufficiently large product root.')
    root_fs = filesystem(raw, root)
    require(root_fs['type'] == 'ext4', 'The selected installed root must be ext4.')
    inventory = efi_inventory(raw, table)
    require(inventory == snapshot['report'].get('efi'), 'Raw EFI bytes no longer match the readback report.')
    prefix = '/EFI/'+PRODUCTS[product]+'/'
    matches = []
    for entry in inventory:
        files = [item for item in entry['files'] if item['path'].startswith(prefix)]
        if files:
            esp = next(p for p in table['partitions'] if p['number'] == entry['partition'])
            matches.append((esp, files))
    require(len(matches) == 1, 'Expected exactly one ESP containing the selected product vendor files.')
    esp, files = matches[0]
    require(any(item['path'] == prefix+'grubx64.efi' and item['bytes'] > 1024 for item in files),
            'The selected product EFI loader is missing.')
    esp_fs = filesystem(raw, esp)
    require(esp_fs['type'] == 'vfat', 'The product ESP must be FAT.')
    image = str(raw)+'@@'+str(esp['start']*512)
    metadata_bytes = bounded_output(['mtype', '-i', image,
        '::/EFI/BitcoinCore/installed-'+product+'.json'], 64*1024)
    metadata = decode_json(metadata_bytes, 64*1024)
    wanted = {'schema': 1, 'product': product, 'boot_id': PRODUCTS[product],
              'disk_guid': table['disk_guid'], 'root_partuuid': root['partition_guid'],
              'root_fsuuid': root_fs['uuid'], 'esp_partuuid': esp['partition_guid'],
              'esp_fsuuid': esp_fs['uuid'], 'serial': snapshot['disk']['serial']}
    require(type(metadata.get('schema')) is int
            and all(metadata.get(key) == value for key, value in wanted.items()),
            'Installed product metadata does not bind this root, ESP and fixture disk.')
    result = dict(product=product, disk_guid=table['disk_guid'], root=part_record(root),
                  root_filesystem=root_fs, root_sha256=root_sha(raw, root),
                  esp=part_record(esp), esp_filesystem=esp_fs,
                  esp_identity=fat_identity(raw, esp), vendor_files=files,
                  installed_record_sha256=hashlib.sha256(metadata_bytes).hexdigest())
    require(stamp(raw) == snapshot['raw_stamp'], 'Raw readback changed during inspection.')
    require(not snapshot['fixture'].active(), 'Stop the fixture before recording preservation evidence.')
    return result


def output_path(fixture, product, number, label=None):
    require(product in PRODUCTS and type(number) is int and 1 <= number <= 4096,
            'Invalid product or partition number.')
    suffix = ''
    if label is not None:
        require(re.fullmatch(r'[A-Za-z0-9_-]{1,48}', label), 'Use a fresh simple comparison label.')
        suffix = '-'+label
    return plain(fixture.root/f'first-os-{product}-p{number}{suffix}.json')


def write_new(path, record):
    path = plain(path)
    with path.open('x') as stream:
        json.dump(record, stream, indent=2); stream.write('\n')


def capture(fixture, report_name, product, number):
    output = output_path(fixture, product, number)
    require(not output.exists(), 'The first-OS baseline already exists; do not replace it.')
    snapshot = load_snapshot(fixture, report_name)
    fingerprint = inspect(snapshot, product, number)
    result = dict(kind='settings-first-os-baseline-v1', product=product,
                  partition_number=number, seed_fixture=snapshot['seed_fixture'],
                  disk=snapshot['disk'], raw=snapshot['raw'].name,
                  raw_stamp=snapshot['raw_stamp'], readback=report_name,
                  readback_sha256=snapshot['report_sha256'], fingerprint=fingerprint,
                  created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    write_new(output, result)
    return dict(status='captured', baseline=str(output), root_bytes=fingerprint['root']['bytes'],
                root_sha256=fingerprint['root_sha256'], vendor_files=fingerprint['vendor_files'])


def compare(fixture, report_name, product, number, label):
    output = output_path(fixture, product, number, label)
    require(not output.exists(), 'Use a fresh comparison label.')
    baseline_path = output_path(fixture, product, number)
    baseline, baseline_sha = read_json(baseline_path)
    require(baseline.get('kind') == 'settings-first-os-baseline-v1'
            and baseline.get('product') == product and baseline.get('partition_number') == number,
            'First-OS baseline does not match the requested product/partition.')
    snapshot = load_snapshot(fixture, report_name)
    require(snapshot['seed_fixture'] == baseline.get('seed_fixture')
            and snapshot['disk'] == baseline.get('disk'), 'First-OS baseline belongs to another fixture.')
    original_raw = member(fixture, baseline.get('raw'), RAW_NAME)
    require(original_raw != snapshot['raw'], 'Use the second installation readback, not the baseline image.')
    # Stat metadata is a provenance sanity check, not a second digest of the
    # historical raw file. Byte preservation compares its captured root SHA256
    # with the new selected-root SHA256 below, independent of clock precision.
    require(stamp(original_raw) == baseline.get('raw_stamp'), 'Original first-OS raw metadata changed.')
    original_report = member(fixture, baseline.get('readback'), REPORT_NAME)
    _, report_sha = read_json(original_report)
    require(report_sha == baseline.get('readback_sha256'), 'Original first-OS readback report changed.')
    current = inspect(snapshot, product, number)
    before = baseline.get('fingerprint')
    require(isinstance(before, dict) and before.keys() == current.keys(), 'Incomplete first-OS baseline.')
    differences = [key for key in current if current[key] != before[key]]
    result = dict(kind='settings-first-os-comparison-v1', status='failed' if differences else 'passed',
                  baseline=baseline_path.name, baseline_sha256=baseline_sha,
                  readback=report_name, readback_sha256=snapshot['report_sha256'],
                  inspected_raw=snapshot['raw'].name, fingerprint=current,
                  differences=differences,
                  scope='Every byte of the selected first root; original product EFI vendor files and installation record; root/ESP identities and boundaries',
                  created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    write_new(output, result)
    require(not differences, 'First installed OS changed: '+', '.join(differences)+'; see '+str(output))
    return dict(status='passed', report=str(output), root_bytes=current['root']['bytes'],
                root_sha256=current['root_sha256'], vendor_files=current['vendor_files'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['capture', 'compare'])
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--readback', required=True, help='Existing preservation-*.json filename')
    parser.add_argument('--product', required=True, choices=tuple(PRODUCTS))
    parser.add_argument('--partition', required=True, type=int)
    parser.add_argument('--label', help='Fresh label for a comparison result')
    args = parser.parse_args()
    fixture = Fixture(args.root)
    if args.action == 'capture':
        result = capture(fixture, args.readback, args.product, args.partition)
    else:
        require(args.label, 'Comparison requires a fresh --label.')
        result = compare(fixture, args.readback, args.product, args.partition, args.label)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
