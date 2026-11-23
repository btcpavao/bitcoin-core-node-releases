#!/usr/bin/python3
"""Drive only owned, offline QEMU fixtures for the Settings/dual-boot candidate.

The controller never attaches a host block device. Native wizard choices are
made from retained current screenshots; this does not preseed an installation.
Readback converts stopped owned qcow2 images into sparse regular files, without
mounting guest filesystems or requiring host root privileges.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import time


def require(value, message):
    if not value:
        raise RuntimeError(message)


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, timeout=kwargs.pop('timeout', 120), **kwargs)


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def plain(path):
    path = Path(os.path.abspath(path))
    require(',' not in str(path) and '\n' not in str(path), 'Unsupported fixture path.')
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'Symlinked fixture path refused.')
    return path


class Fixture:
    def __init__(self, directory):
        self.root = plain(directory)
        require(self.root.is_dir() and self.root.stat().st_uid == os.getuid(), 'Fixture must be owned.')
        self.file = self.root / 'fixture.json'
        self.record = json.loads(self.file.read_text())
        require(self.record['kind'] == 'settings-dualboot-vm-v1', 'Unknown fixture.')
        for disk in self.record['disks']:
            path = plain(self.root / disk['file'])
            require(path.parent == self.root and path.is_file(), 'Only fixture disk files are allowed.')
        self.socket = self.root / 'qmp.sock'

    def save(self):
        self.file.write_text(json.dumps(self.record, indent=2) + '\n')

    def active(self):
        process = self.record.get('process')
        if not process:
            return False
        p = Path('/proc') / str(process['pid'])
        if not p.exists():
            return False
        argv = [s.decode() for s in (p/'cmdline').read_bytes().split(b'\0') if s]
        if not argv:
            return False
        ticks = (p/'stat').read_text().split(') ', 1)[1].split()[19]
        require(p.stat().st_uid == os.getuid() and argv == process['argv'] and ticks == process['ticks'],
                'Recorded QEMU process identity changed.')
        return True

    def qmp(self, command, arguments=None):
        require(self.active(), 'Owned QEMU is not running.')
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(30)
            client.connect(str(self.socket))
            stream = client.makefile('rwb', buffering=0)
            stream.readline()
            for cmd, args in [('qmp_capabilities', {}), (command, arguments or {})]:
                stream.write(json.dumps({'execute': cmd, 'arguments': args}).encode()+b'\n')
                while True:
                    reply = json.loads(stream.readline(1024*1024))
                    require('error' not in reply, str(reply))
                    if 'return' in reply:
                        break
            return reply['return']

    def start(self, iso=None, digest=None, product=None, installed=False):
        require(not self.active(), 'Stop the existing fixture before starting another phase.')
        if self.socket.exists():
            require(stat.S_ISSOCK(self.socket.lstat().st_mode), 'Unexpected QMP path.')
            self.socket.unlink()
        phase = len(self.record.get('boots', [])) + 1
        command = [shutil.which('qemu-system-x86_64'), '-name', 'owned-settings-dualboot',
                   '-machine', 'q35,dump-guest-core=off', '-accel', 'kvm' if os.access('/dev/kvm', os.R_OK|os.W_OK) else 'tcg',
                   '-m', '3072', '-smp', '2', '-display', 'none', '-vga', 'std', '-nic', 'none',
                   '-qmp', 'unix:'+str(self.socket)+',server=on,wait=off', '-monitor', 'none',
                   '-serial', 'file:'+str(self.root/f'boot-{phase}-serial.log'),
                   '-device', 'qemu-xhci,id=usb', '-device', 'usb-tablet', '-no-reboot']
        require(command[0], 'QEMU is not installed.')
        for i, disk in enumerate(self.record['disks']):
            command += ['-drive', f'file={self.root/disk["file"]},if=none,format=qcow2,id=disk{i}',
                        '-device', f'virtio-blk-pci,drive=disk{i},serial={disk["serial"]},bootindex={i+2}']
        media = self.root/'probe-usb.raw'
        if media.is_file():
            command += ['-drive', f'file={media},if=none,format=raw,id=probe-usb',
                        '-device', 'usb-storage,bus=usb.0,drive=probe-usb,removable=on,serial=SETTINGS_QA_USB']
        image_record = None
        if iso:
            image = plain(iso)
            require(image.is_file() and re.fullmatch('[0-9a-f]{64}', digest or ''), 'Exact ISO SHA256 required.')
            require(sha(image) == digest, 'ISO digest mismatch.')
            require(product in ('node','vault'), 'Product must be explicit.')
            command += ['-drive', f'file={image},if=none,id=iso,media=cdrom,readonly=on',
                        '-device', 'ide-cd,drive=iso,bus=ide.1,bootindex='+('9' if installed else '1'),
                        '-boot', 'order='+('c' if installed else 'd')]
            image_record = {'path': str(image), 'sha256': digest, 'product': product}
        else:
            command += ['-boot', 'order=c']
        if self.record['firmware'] == 'uefi':
            command += ['-drive', 'if=pflash,format=raw,readonly=on,file='+self.record['firmware_code'],
                        '-drive', 'if=pflash,format=raw,file='+str(self.root/'vars.fd')]
        log_path = self.root/f'boot-{phase}-qemu.log'
        with log_path.open('xb') as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            require(process.poll() is None, log_path.read_text())
            proc = Path('/proc')/str(process.pid)
            if (proc/'cmdline').read_bytes().split(b'\0')[:-1] == [s.encode() for s in command]:
                break
            time.sleep(.05)
        self.record['process'] = {'pid': process.pid, 'argv': command,
                                 'ticks': (proc/'stat').read_text().split(') ',1)[1].split()[19]}
        self.record.setdefault('boots', []).append({'number': phase, 'iso': image_record, 'installed':installed or not iso,'time': time.time()})
        self.save()
        return {'pid': process.pid, 'boot': phase, 'iso': image_record}

    def capture(self, label='screen'):
        from PIL import Image
        require(re.fullmatch('[a-zA-Z0-9_-]{1,64}', label), 'Invalid screenshot label.')
        output = self.root/f'{time.time_ns()}-{label}.png'
        ppm = output.with_suffix('.ppm')
        self.qmp('screendump', {'filename': str(ppm)})
        with Image.open(ppm) as im:
            im.save(output)
        ppm.unlink()
        return output

    def key(self, keys):
        require(all(re.fullmatch('[a-z0-9_]+', key) for key in keys), 'Invalid QEMU keys.')
        def events(down, values):
            return [{'type':'key','data':{'down':down,'key':{'type':'qcode','data':k}}} for k in values]
        self.qmp('input-send-event', {'events': events(True, keys)})
        self.qmp('input-send-event', {'events': events(False, reversed(keys))})
        time.sleep(.06)

    def text(self, value):
        normal = dict(zip(' -=[];\'`,./\\\n\t', ['spc','minus','equal','bracket_left','bracket_right','semicolon','apostrophe','grave_accent','comma','dot','slash','backslash','ret','tab']))
        shifted = dict(zip('!@#$%^&*()_+{}:"<>?|~', ['1','2','3','4','5','6','7','8','9','0','minus','equal','bracket_left','bracket_right','semicolon','apostrophe','comma','dot','slash','backslash','grave_accent']))
        for ch in value:
            if ch.isascii() and ch.isalnum():
                self.key((['shift'] if ch.isupper() else [])+[ch.lower()])
            elif ch in normal:
                self.key([normal[ch]])
            elif ch in shifted:
                self.key(['shift', shifted[ch]])
            else:
                raise ValueError('Only ASCII guest fixture input is accepted.')

    def click(self, observed, point):
        from PIL import Image
        observed = plain(observed)
        require(observed.parent == self.root and observed.is_file(), 'Click requires this fixture screenshot.')
        require(time.time()-observed.stat().st_mtime < 300, 'Take a fresh screenshot before clicking.')
        current = self.capture('before-click')
        with Image.open(observed) as a, Image.open(current) as b:
            require(a.size == b.size, 'Guest display geometry changed.')
            width, height = a.size
        x,y = map(int, point.split(','))
        require(0 <= x < width and 0 <= y < height, 'Click outside observed display.')
        self.qmp('input-send-event', {'events':[
            {'type':'abs','data':{'axis':axis,'value':round(v*32767/(size-1))}}
            for axis,v,size in [('x',x,width),('y',y,height)]]})
        self.qmp('input-send-event', {'events':[{'type':'btn','data':{'button':'left','down':True}}]})
        self.qmp('input-send-event', {'events':[{'type':'btn','data':{'button':'left','down':False}}]})
        self.record.setdefault('clicks', []).append({'observed': observed.name, 'current': current.name, 'point':[x,y]})
        self.save()

    def stop(self):
        if self.active():
            self.qmp('quit')
            until = time.monotonic()+20
            while self.active() and time.monotonic() < until:
                time.sleep(.1)
            require(not self.active(), 'Owned QEMU did not stop.')
        return {'stopped': True}

    def wait_text(self, expression, label, timeout):
        """Retain each real frame; no input is sent while waiting."""
        from PIL import Image
        pattern = re.compile(expression, re.I)
        deadline, heartbeat = time.monotonic()+timeout, 0
        latest = ''
        while time.monotonic() < deadline:
            observed = self.capture(label)
            enlarged = observed.with_name(observed.stem+'-ocr.png')
            with Image.open(observed) as im:
                im.resize((im.width*3,im.height*3),Image.Resampling.LANCZOS).save(enlarged)
            result = run([os.environ.get('TESSERACT_EXECUTABLE','tesseract'),str(enlarged),
                          'stdout','-l','eng','--psm','11'], capture_output=True,text=True,timeout=30)
            latest = result.stdout
            observed.with_suffix('.txt').write_text(latest)
            if pattern.search(latest):
                return {'image':str(observed),'text':latest,'matched':expression}
            require('installation failed' not in latest.lower(), 'Native installer failure: '+latest)
            if time.monotonic() >= heartbeat:
                print(json.dumps({'waiting':label,'last_text':latest[-500:]}),flush=True)
                heartbeat = time.monotonic()+30
            time.sleep(2)
        raise RuntimeError('Screen deadline: '+expression+'; last screen: '+latest)

    def readback(self, index, label):
        require(not self.active(), 'Readback is only allowed after QEMU stops.')
        require(re.fullmatch('[a-zA-Z0-9_-]{1,64}', label), 'Invalid readback label.')
        disk = self.record['disks'][index]
        output = self.root/f'readback-{label}-disk{index}.raw'
        require(not output.exists(), 'Readback output already exists.')
        run(['qemu-img','convert','-f','qcow2','-O','raw','-S','4k',str(self.root/disk['file']),str(output)], timeout=600)
        table = json.loads(run(['/usr/sbin/sfdisk','--json',str(output)], capture_output=True, text=True).stdout)['partitiontable']
        sector = table.get('sectorsize',512)
        partitions = []
        with output.open('rb') as handle:
            for part in table['partitions']:
                handle.seek(part['start']*sector)
                remaining = part['size']*sector
                digest = hashlib.sha256()
                while remaining:
                    data = handle.read(min(8*1024*1024, remaining))
                    require(data, 'Truncated fixture disk.')
                    digest.update(data); remaining -= len(data)
                partitions.append({**part,'sha256': digest.hexdigest()})
        record = {'disk': disk, 'raw': output.name, 'table': table, 'partitions': partitions}
        (output.with_suffix('.json')).write_text(json.dumps(record,indent=2)+'\n')
        return record


def create(args):
    root = plain(args.root)
    require(not root.exists(), 'Use a new fixture directory.')
    sizes = [int(x) for x in args.disks.split(',')]
    require(1 <= len(sizes) <= 2 and all(16 <= x <= 2048 for x in sizes), 'One or two bounded virtual disks required.')
    root.mkdir(mode=0o700, parents=True)
    record = {'kind':'settings-dualboot-vm-v1','firmware':args.firmware,'disks':[],'boots':[]}
    for i, size in enumerate(sizes):
        name = f'disk-{i}.qcow2'
        run(['qemu-img','create','-f','qcow2',str(root/name),f'{size}G'],capture_output=True)
        # Virtio-blk exposes at most 20 serial bytes; keep the index visible.
        record['disks'].append({'file':name,'gib':size,'serial':f'QA_SETTINGS_DISK_{i}'})
    if args.firmware == 'uefi':
        code = plain('/usr/share/OVMF/OVMF_CODE_4M.fd')
        variables = plain('/usr/share/OVMF/OVMF_VARS_4M.fd')
        require(code.is_file() and variables.is_file(), 'OVMF is unavailable.')
        record['firmware_code'] = str(code)
        record['firmware_sha256'] = sha(code)
        shutil.copyfile(variables,root/'vars.fd')
    (root/'fixture.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['create','start','screen','key','type','click','status','stop','poweroff','wait','readback'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--disks',default='64')
    parser.add_argument('--firmware',choices=['uefi','bios'],default='uefi')
    parser.add_argument('--iso',type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--product',choices=['node','vault'])
    parser.add_argument('--installed',action='store_true')
    parser.add_argument('--label',default='screen')
    parser.add_argument('--keys')
    parser.add_argument('--text')
    parser.add_argument('--observed',type=Path)
    parser.add_argument('--point')
    parser.add_argument('--disk',type=int,default=0)
    parser.add_argument('--contains')
    parser.add_argument('--timeout',type=int,default=180)
    args=parser.parse_args()
    if args.action=='create':
        result=create(args)
    else:
        fixture=Fixture(args.root)
        if args.action=='start':result=fixture.start(args.iso,args.sha256,args.product,args.installed)
        elif args.action=='screen':result={'image':str(fixture.capture(args.label))}
        elif args.action=='key':fixture.key(args.keys.split('+'));result={'keys_sent':True}
        elif args.action=='type':fixture.text(args.text);result={'text_sent':True}
        elif args.action=='click':fixture.click(args.observed,args.point);result={'clicked':True}
        elif args.action=='status':result=fixture.qmp('query-status') if fixture.active() else {'running':False}
        elif args.action=='stop':result=fixture.stop()
        elif args.action=='poweroff':result=fixture.qmp('system_powerdown')
        elif args.action=='wait':result=fixture.wait_text(args.contains,args.label,args.timeout)
        elif args.action=='readback':result=fixture.readback(args.disk,args.label)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
