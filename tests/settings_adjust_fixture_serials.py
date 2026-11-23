#!/usr/bin/python3
"""One-time metadata-only serial correction for five fresh owned QA fixtures."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time

from settings_dualboot_vm import Fixture, plain, require
from settings_disk_readback import owned_regular
from settings_first_os_preservation import read_json, stamp


NAMES = ('qa-node-first', 'qa-vault-first', 'qa-two-disks', 'qa-bios-node', 'qa-bios-vault')


def digest(path):
    path = owned_regular(path)
    require(path.stat().st_size <= 256*1024**2, 'Do not rehash a whole large raw readback.')
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def fresh(fixture):
    require(not fixture.active() and fixture.record.get('boots') == []
            and not fixture.record.get('process'), 'Serial changes require a stopped, never-booted fixture.')


def adjusted(value, disks):
    value = deepcopy(value)
    changes = []

    def visit(item, location):
        if isinstance(item, dict):
            for index, disk in enumerate(disks):
                if all(item.get(key) == disk[key] for key in ('file', 'gib', 'serial')):
                    serial = 'QA_SETTINGS_DISK_'+str(index)
                    changes.append({'json_location': location, 'old': disk['serial'], 'new': serial})
                    item['serial'] = serial
                    break
            for key, child in item.items():
                visit(child, location+'/'+str(key))
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, location+'/'+str(index))

    visit(value, '')
    require('OWNED_SETTINGS_DISK_' not in json.dumps(value), 'Unrecognized old serial reference in JSON evidence.')
    return value, changes


def prepare(base, name):
    require(name in NAMES, 'Fixture is not in the authorized fresh-fixture set.')
    fixture = Fixture(plain(base/name)); fresh(fixture)
    require(not plain(fixture.root/'serial-adjustment.json').exists()
            and not plain(fixture.root/'serial-adjustment-originals').exists(), 'Serial adjustment already started.')
    for index, disk in enumerate(fixture.record['disks']):
        require(disk['serial'] == 'OWNED_SETTINGS_DISK_'+str(index), 'Unexpected existing fixture serial.')
    reports, preserved, raw_records = [], [], []
    for path in sorted(fixture.root.iterdir()):
        path = owned_regular(path)
        if path.suffix == '.json':
            value, old_sha = read_json(path)
            updated, changes = adjusted(value, fixture.record['disks'])
            if changes:
                data = (json.dumps(updated, indent=2)+'\n').encode()
                reports.append({'name': path.name, 'old_sha256': old_sha,
                                'new_sha256': hashlib.sha256(data).hexdigest(),
                                'changes': changes, 'old_bytes': path.read_bytes(), 'new_bytes': data})
            else:
                preserved.append({'name': path.name, 'sha256': old_sha, 'stamp': stamp(path)})
        elif path.stat().st_size <= 256*1024**2:
            preserved.append({'name': path.name, 'sha256': digest(path), 'stamp': stamp(path)})
        else:
            require(path.suffix == '.raw', 'Unexpected large non-readback fixture file.')
            source = path.with_suffix('.json')
            report, report_sha = read_json(source)
            raw_records.append({'name': path.name, 'stamp': stamp(path),
                                'preparation_report': source.name, 'preparation_report_sha256': report_sha,
                                'recorded_logical_sha256': report.get('sha256'),
                                'whole_raw_digest_recomputed': False})
    require(any(r['name'] == 'fixture.json' for r in reports), 'Fixture declaration would not be adjusted.')
    changed_names = {record['name'] for record in reports}
    for record in raw_records:
        name = record['preparation_report']
        record['preparation_report_reference'] = (
            'serial-adjustment-originals/'+name if name in changed_names else name)
    return fixture, reports, preserved, raw_records


def atomic_json(path, value):
    temporary = plain(path.with_name(path.name+'.new'))
    with temporary.open('x') as stream:
        json.dump(value, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, plain(path))


def apply(plan):
    fixture, reports, preserved, raw_records = plan
    fresh(Fixture(fixture.root))
    archive = plain(fixture.root/'serial-adjustment-originals'); archive.mkdir(mode=0o700)
    for record in reports:
        path = fixture.root/record['name']
        require(digest(path) == record['old_sha256'], 'JSON evidence changed after preflight.')
        with (archive/record['name']).open('xb') as output:
            output.write(record['old_bytes'])
    public = [{key: value for key, value in r.items() if key not in ('old_bytes', 'new_bytes')} for r in reports]
    evidence = {'kind': 'settings-fixture-serial-adjustment-v1', 'status': 'prepared',
                'fixture': str(fixture.root), 'reason': 'Keep unique disk index within the 20-byte virtio-blk serial field',
                'changed_json': public, 'unchanged_files': preserved, 'unchanged_raw_readbacks': raw_records,
                'original_json_directory': archive.name,
                'scope': 'Only exact disk serial values in fixture/baseline JSON; no disk, firmware, raw readback or media writes',
                'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    report_path = plain(fixture.root/'serial-adjustment.json'); atomic_json(report_path, evidence)
    for record in reports:
        path = plain(fixture.root/record['name'])
        temporary = plain(path.with_name(path.name+'.serial-new'))
        with temporary.open('xb') as output:
            output.write(record['new_bytes']); output.flush(); os.fsync(output.fileno())
        require(digest(path) == record['old_sha256'], 'JSON evidence changed during adjustment.')
        os.replace(temporary, path)
        require(digest(path) == record['new_sha256'], 'Adjusted JSON does not match its recorded digest.')
    fresh(Fixture(fixture.root))
    for record in preserved:
        path = fixture.root/record['name']
        require(stamp(path) == record['stamp'] and digest(path) == record['sha256'],
                'An unrelated fixture file changed: '+record['name'])
    for record in raw_records:
        require(stamp(fixture.root/record['name']) == record['stamp'], 'A raw readback metadata tuple changed.')
    for record in reports:
        require(digest(archive/record['name']) == record['old_sha256'], 'Original JSON archive differs.')
    evidence['status'] = 'completed'; atomic_json(report_path, evidence)
    return {'fixture': fixture.root.name, 'status': 'completed',
            'serials': [d['serial'] for d in Fixture(fixture.root).record['disks']],
            'changed_json': [r['name'] for r in reports], 'evidence': str(report_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    args = parser.parse_args(); base = plain(args.base)
    # Validate every requested fixture before modifying any of them.
    plans = [prepare(base, name) for name in NAMES]
    for plan in plans:
        print(json.dumps(apply(plan)), flush=True)


if __name__ == '__main__':
    main()
