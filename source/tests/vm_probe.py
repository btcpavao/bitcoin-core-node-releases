#!/usr/bin/python3
"""Owned QEMU fixture only; no host disks or external networks are attached.

Start one live BIOS/UEFI image, inspect QMP screenshots and send keyboard input
only to that VM. Native installation still requires observed wizard checks.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('--mouse-button', choices=['left','middle','right'], default='left')
parser.add_argument('action', choices=['start', 'screen', 'key', 'type', 'click', 'status', 'stop', 'installed', 'usb-attach', 'usb-detach'])
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--iso', type=Path)
parser.add_argument('--uefi', action='store_true')
parser.add_argument('--keys')
parser.add_argument('--text')
parser.add_argument('--label')
parser.add_argument('--point', help='x,y from a previously observed VM screenshot')
parser.add_argument('--observed', type=Path)
parser.add_argument('--usb', type=Path)
args = parser.parse_args()
root = args.root.absolute()
if root.is_symlink() or not root.is_relative_to(Path.home()/'node-v1-validation'):
    raise SystemExit('Please use an owned fixture directory under ~/node-v1-validation.')


def qmp(command, arguments=None):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(15); sock.connect(str(root/'qmp.sock'))
        stream = sock.makefile('rwb', buffering=0)
        stream.readline()
        stream.write(b'{"execute":"qmp_capabilities"}\n')
        while 'return' not in json.loads(stream.readline()): pass
        stream.write(json.dumps({'execute': command, 'arguments': arguments or {}}).encode()+b'\n')
        while True:
            reply = json.loads(stream.readline())
            if 'error' in reply: raise RuntimeError(reply['error'])
            if 'return' in reply: return reply['return']


if args.action == 'start':
    if args.iso is None or not args.iso.is_file(): raise SystemExit('Please select an existing ISO.')
    root.mkdir(parents=True, exist_ok=False)
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', str(root/'disk.qcow2'), '48G'], check=True)
    command = ['qemu-system-x86_64', '-name', 'owned-core-node-acceptance',
        '-machine', 'q35', '-accel', 'kvm' if os.access('/dev/kvm', os.R_OK|os.W_OK) else 'tcg',
        '-m', '2048', '-smp', '2', '-display', 'none', '-vga', 'std', '-nic', 'none',
        '-qmp', 'unix:'+str(root/'qmp.sock')+',server=on,wait=off',
        '-monitor', 'none', '-serial', 'file:'+str(root/'serial.log'),
        '-device', 'qemu-xhci,id=xhci', '-device', 'usb-tablet',
        '-drive', 'file='+str(root/'disk.qcow2')+',format=qcow2,if=none,id=node-disk',
        '-device', 'virtio-blk-pci,drive=node-disk,serial=NODE-OWNED-ACCEPTANCE',
        '-cdrom', str(args.iso.absolute()), '-boot', 'order=c,once=d']
    if args.uefi:
        code = Path('/usr/share/OVMF/OVMF_CODE_4M.fd'); variables = Path('/usr/share/OVMF/OVMF_VARS_4M.fd')
        if not code.is_file() or not variables.is_file(): raise SystemExit('OVMF firmware unavailable.')
        shutil.copyfile(variables, root/'vars.fd')
        command += ['-drive', 'if=pflash,format=raw,readonly=on,file='+str(code), '-drive', 'if=pflash,format=raw,file='+str(root/'vars.fd')]
    with (root/'qemu.log').open('xb') as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    time.sleep(.3)
    if process.poll() is not None: raise SystemExit((root/'qemu.log').read_text())
    (root/'fixture.json').write_text(json.dumps({'pid': process.pid, 'command': command, 'iso': str(args.iso), 'uefi': args.uefi}))
    print(json.dumps({'pid': process.pid, 'fixture': str(root)}))
else:
    record = json.loads((root/'fixture.json').read_text())
    cmdline = Path('/proc')/str(record['pid'])/'cmdline'
    if not cmdline.exists() or os.fsencode(str(root/'qmp.sock')) not in cmdline.read_bytes():
        raise SystemExit('The recorded owned VM is no longer running.')
    if args.action == 'status': print(json.dumps(qmp('query-status')))
    elif args.action == 'key':
        if not args.keys: raise SystemExit('Please provide QEMU key names separated by hyphens.')
        print(qmp('human-monitor-command', {'command-line': 'sendkey '+args.keys}))
        time.sleep(.3)
    elif args.action == 'type':
        if args.text is None: raise SystemExit('Please provide ASCII fixture text.')
        mapping={' ':'spc','\n':'ret','\t':'tab','-':'minus','_':'shift-minus','.':'dot',
            '/':'slash',':':'shift-semicolon',';':'semicolon',"'":'apostrophe','"':'shift-apostrophe',
            '=':'equal','+':'shift-equal',',':'comma','(':'shift-9',')':'shift-0',
            '[':'bracket_left',']':'bracket_right','{':'shift-bracket_left','}':'shift-bracket_right',
            '!':'shift-1','@':'shift-2','#':'shift-3','$':'shift-4','%':'shift-5','&':'shift-7',
            '*':'shift-8','?':'shift-slash','>':'shift-dot','<':'shift-comma','|':'shift-backslash',
            '\\':'backslash','`':'grave_accent','~':'shift-grave_accent'}
        for character in args.text:
            if character.isascii() and character.isalnum():
                key=('shift-' if character.isupper() else '')+character.lower()
            elif character in mapping:key=mapping[character]
            else:raise SystemExit('Unsupported fixture text character.')
            qmp('human-monitor-command', {'command-line':'sendkey '+key+' 20'})
            time.sleep(.5 if character in ('\n','\t') else .08)
        print('Fixture text entered into owned VM.')
    elif args.action == 'click':
        if not args.label and not args.point:raise SystemExit('Please supply an observed word or position.')
        image=root/('click-observation-'+str(time.time_ns())+'.ppm')
        qmp('screendump',{'filename':str(image)})
        from PIL import Image
        width,height=Image.open(image).size
        candidates=[]
        if args.point:
            if not args.observed or args.observed.parent != root or not args.observed.is_file():
                raise SystemExit('Please reference the observed screenshot in this fixture.')
            x,y=map(int,args.point.split(','))
            if Image.open(args.observed).size!=(width,height) or not (0<=x<width and 0<=y<height):
                raise SystemExit('Screenshot size or position mismatch.')
            candidates.append((x,y))
        else:
            ocr=subprocess.run(['tesseract',str(image),'stdout','--psm','11','tsv'],capture_output=True,text=True,check=True)
            for line in ocr.stdout.splitlines()[1:]:
                fields=line.split('\t')
                if len(fields)==12 and fields[11].strip().strip('&')==args.label:
                    x,y,w,h=map(int,fields[6:10]);candidates.append((x+w/2,y+h/2))
        if len(candidates)!=1:raise SystemExit('Expected exactly one visible '+args.label+' label; observed '+str(len(candidates)))
        x,y=candidates[0]
        qmp('input-send-event',{'events':[{'type':'abs','data':{'axis':'x','value':int(x*32767/width)}},{'type':'abs','data':{'axis':'y','value':int(y*32767/height)}}]})
        qmp('input-send-event',{'events':[{'type':'btn','data':{'button':args.mouse_button,'down':True}}]})
        time.sleep(.1)
        qmp('input-send-event',{'events':[{'type':'btn','data':{'button':args.mouse_button,'down':False}}]})
        time.sleep(.15)
        qmp('input-send-event',{'events':[{'type':'abs','data':{'axis':'x','value':128}},{'type':'abs','data':{'axis':'y','value':128}}]})
        print(json.dumps({'clicked':args.label,'pixel':[x,y],'observed_frame':str(image)}))
    elif args.action == 'usb-attach':
        usb=args.usb.absolute() if args.usb else None
        if not usb or not usb.is_relative_to(Path.home()/'node-v1-validation') or usb.is_symlink() or not usb.is_file():
            raise SystemExit('Please select an owned regular USB fixture image.')
        qmp('blockdev-add',{'node-name':'node-test-usb','driver':'raw','file':{'driver':'file','filename':str(usb)}})
        qmp('device_add',{'driver':'usb-storage','bus':'xhci.0','drive':'node-test-usb','id':'node-test-usb-device','removable':True,'serial':'NODE_TEST_USB'})
        record['usb']=str(usb);(root/'fixture.json').write_text(json.dumps(record));print('Attached owned USB fixture.')
    elif args.action == 'usb-detach':
        qmp('device_del',{'id':'node-test-usb-device'})
        for _ in range(100):
            try:qmp('blockdev-del',{'node-name':'node-test-usb'});break
            except RuntimeError:time.sleep(.05)
        else:raise SystemExit('USB fixture did not detach.')
        record.pop('usb',None);(root/'fixture.json').write_text(json.dumps(record));print('Detached owned USB fixture.')
    elif args.action == 'installed':
        qmp('quit')
        for _ in range(100):
            if not cmdline.exists() or not cmdline.read_bytes():break
            time.sleep(.05)
        else:raise SystemExit('Owned live VM did not stop.')
        command=list(record['command']);index=command.index('-cdrom');del command[index:index+2]
        command[command.index('-boot')+1]='c'
        with (root/'qemu-installed.log').open('ab') as log:
            process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        record.update(pid=process.pid,command=command,phase='installed')
        (root/'fixture.json').write_text(json.dumps(record));print(json.dumps(record))
    elif args.action == 'stop': qmp('quit'); print('Owned VM stopped.')
    elif args.action == 'screen':
        ppm = root/('screen-'+str(time.time_ns())+'.ppm')
        qmp('screendump', {'filename': str(ppm)})
        from PIL import Image
        output = ppm.with_suffix('.png'); Image.open(ppm).save(output); ppm.unlink()
        print(str(output))
