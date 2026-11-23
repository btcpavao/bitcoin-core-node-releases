#!/usr/bin/python3
"""Native qemu-img/mtools smoke using a fresh synthetic, nonbooted fixture."""
import argparse
import hashlib
import json
from pathlib import Path

from settings_dualboot_vm import Fixture, create, require, run
from settings_disk_readback import checkpoint, compare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    create(argparse.Namespace(root=args.root, disks='16', firmware='bios'))
    fixture = Fixture(args.root)
    raw = fixture.root/'synthetic.raw'
    with raw.open('xb') as image:
        image.truncate(16*1024**3)
    run(['/usr/sbin/sfdisk', str(raw)], input='label: gpt\nstart=2048,size=65536,type=U,name=EFI_QA\n',
        text=True, capture_output=True)
    run(['/usr/sbin/mkfs.fat', '-F', '16', '-n', 'QATEST', '--offset', '2048', str(raw), '32768'],
        capture_output=True)
    image = str(raw)+'@@1048576'
    run(['mmd', '-i', image, '::/EFI', '::/EFI/BOOT', '::/EFI/CORE_NODE'], capture_output=True)
    data = fixture.root/'synthetic-efi.bin'
    payload = b'This is a synthetic inspection fixture, not a bootable EFI binary.\n'
    data.write_bytes(payload)
    config = fixture.root/'synthetic-grub.cfg'
    config.write_text('set timeout=10\nmenuentry "Synthetic EFI inspection" {}\n')
    run(['mcopy', '-i', image, str(data), '::/EFI/BOOT/BOOTX64.EFI'], capture_output=True)
    run(['mcopy', '-i', image, str(config), '::/EFI/CORE_NODE/grub.cfg'], capture_output=True)
    target = fixture.root/'disk-0.qcow2'
    target.unlink()
    run(['qemu-img', 'convert', '-f', 'raw', '-O', 'qcow2', str(raw), str(target)], timeout=60)
    raw.unlink()
    baseline = checkpoint(fixture, 0, 'native-smoke')
    records = {record['path']: record for part in baseline['efi'] for record in part['files']}
    require(records['/EFI/BOOT/BOOTX64.EFI']['sha256'] == hashlib.sha256(payload).hexdigest(),
            'Native EFI bytes were not read correctly.')
    require(records['/EFI/CORE_NODE/grub.cfg']['text'] == config.read_text(), 'Native GRUB config differs.')
    same = compare(fixture, 0, 'checkpoint-native-smoke-disk0.json', 'unchanged')
    require(same['equal'], 'An unchanged qcow2 failed the native comparison.')
    run(['qemu-io', '-f', 'qcow2', '-c', 'write -P 123 134217728 512', str(target)], capture_output=True)
    try:
        compare(fixture, 0, 'checkpoint-native-smoke-disk0.json', 'changed-free-sector')
    except RuntimeError as exc:
        require('other fixture disk changed' in str(exc), 'Unexpected changed-disk comparison error.')
    else:
        raise RuntimeError('An altered unallocated sector escaped the whole-disk comparison.')
    evidence = dict(status='passed', kind='settings-native-readback-smoke-v1',
                    checks=['Both GPT copies validated', 'EFI binary hash and GRUB text match',
                            'Unchanged whole qcow2 matches retained raw checkpoint',
                            'One altered unallocated sector is detected'],
                    logical_bytes=baseline['virtual_bytes'], allocated_baseline_bytes=baseline['allocated_bytes'])
    (fixture.root/'native-readback-result.json').write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
