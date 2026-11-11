#!/usr/bin/python3
"""Installed-OS acceptance through an owned QEMU console and removable media."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--usb', type=Path, required=True)
parser.add_argument('--resume', choices=['live', 'graphical', 'installed', 'root'], default='live')
parser.add_argument('--extra', choices=['network','maintenance','tor','vpn'])
parser.add_argument('--keep-running', action='store_true')
parser.add_argument('--skip-initial', action='store_true')
args = parser.parse_args()
root = args.root.absolute()
assert root.is_relative_to(Path.home()/'node-v1-validation') and not root.is_symlink()
record = json.loads((root/'fixture.json').read_text())
nic=record['command'][record['command'].index('-nic')+1]
assert nic=='none' or (args.extra=='tor' and root.name=='tor-public-5dde561' and nic=='user,model=virtio-net-pci,mac=52:54:00:31:00:01')
assert str(root/'disk.qcow2') in ' '.join(record['command'])
probe = Path(__file__).with_name('vm_probe.py')
report = {'source_iso': record['iso'], 'screens': [], 'checks': []}

def call(action, *options):
    return subprocess.run(['python3', str(probe), action, '--root', str(root), *options],
        capture_output=True, text=True, check=True, timeout=90).stdout.strip()

def screen():
    path = Path(call('screen'))
    result = subprocess.run(['tesseract', str(path), 'stdout', '--psm', '6'],
        capture_output=True, text=True, check=True, timeout=30).stdout
    if 'root@' not in result and 'nodecheck@' not in result:
        from PIL import Image
        with Image.open(path) as frame:
            crop=frame.crop((frame.width//4,frame.height//4,frame.width*3//4,frame.height*3//4))
            center=root/'login-center.png';crop.resize((crop.width*3,crop.height*3)).save(center)
        result+='\n'+subprocess.run(['tesseract',str(center),'stdout','--psm','6'],capture_output=True,text=True,check=True).stdout
    return path, result

def wait(label, predicate, timeout=180, tty=False):
    until = time.monotonic()+timeout
    last_key = last_status = 0
    while time.monotonic() < until:
        path, text = screen()
        if tty and 'gnu grub' in text.lower() and 'gnu/linux' in text.lower():
            call('key', '--keys', 'ret'); last_key=time.monotonic()
        elif tty and time.monotonic()-last_key > 15:
            call('key', '--keys', 'ctrl-alt-f2'); last_key=time.monotonic()
        if predicate(text.lower()):
            report['screens'].append({'label': label, 'image':str(path), 'text':text})
            print(json.dumps({'observed':label, 'image':str(path)}), flush=True)
            return text
        if time.monotonic()-last_status > 30:
            print('Waiting for '+label, flush=True); last_status=time.monotonic()
        time.sleep(3)
    raise RuntimeError('Deadline: '+label+'; last screen: '+text)

def type_text(text):
    call('type', '--text', text)

def login():
    wait('installed-login', lambda s:'login:' in s, 300, tty=True)
    type_text('nodecheck\n')
    wait('account-password', lambda s:'password:' in s)
    type_text('NodeFixture-2026!\n')
    wait('authenticated-account', lambda s:'nodecheck@node-fixture' in s)
    type_text('sudo -i\n')
    wait('sudo-authentication', lambda s:'password for nodecheck' in s)
    type_text('NodeFixture-2026!\n')
    wait('authenticated-root', lambda s:'root@node-fixture' in s)

def phase(name):
    type_text('clear\n')
    call('usb-attach','--usb',str(args.usb))
    type_text('mkdir -p /mnt/node-test; mount LABEL=NODE_TEST /mnt/node-test\n')
    time.sleep(1)
    script='installed_'+name.split('-')[0]+'_probe.py' if name.startswith(('network','maintenance','tor','vpn')) else 'installed_probe.py'
    while True:
        token=''.join(secrets.choice('2347') for _ in range(12))
        try:
            (root/('token-'+token)).touch(exist_ok=False);break
        except FileExistsError:pass
    type_text('NODE_VM_ACCEPTANCE=1 python3 /mnt/node-test/'+script+' '+name+
        ' --media /mnt/node-test >/mnt/node-test/'+name+'.log 2>&1; r=$?; sync; umount /mnt/node-test; u=$?; echo NODE_TEST_'+token+'_${r}_UNMOUNT_${u}\n')
    pattern='node_test_'+token+r'[_ ]+([0-9o@]+)[_ ]+unmount[_ ]+([0-9o@]+)'
    text=wait('probe-'+name, lambda s:re.search(pattern,s) is not None, 900 if name.startswith('tor') else 360)
    result_match=re.search(pattern,text.lower())
    assert result_match[2].replace('o','0').replace('@','0')=='0','Guest USB unmount did not complete; leaving attached.'
    call('usb-detach')
    for item in (name+'.log','installed-'+name+'-result.json'):
        # A previous FAT copy may be read-only; never wait for an overwrite prompt.
        fresh=root/(token+'-'+item)
        subprocess.run(['mcopy','-i',str(args.usb),'::'+item,str(fresh)],check=True,
            stdin=subprocess.DEVNULL,capture_output=True,timeout=30)
        fresh.replace(root/item)
    assert result_match[1].replace('o','0').replace('@','0')=='0', (root/(name+'.log')).read_text()
    result=json.loads((root/('installed-'+name+'-result.json')).read_text())
    assert result['status']=='passed-covered-checks',result
    report['checks'].append(result)
    print(json.dumps(result),flush=True)

try:
    if args.resume in ('live','graphical'):
        result=json.loads((root/'installer-result.json').read_text())
        assert result['status']=='installed-awaiting-normal-reboot',result
        if args.resume=='live': call('installed')
        wait('graphical-login',lambda s:'log in' in s,300)
        type_text('nodecheck\tNodeFixture-2026!\n')
        wait('installed-home',lambda s:'watch-only' in s,180)
    if args.resume!='root': login()
    if args.extra:
        if not args.skip_initial:phase(args.extra)
        else:
            previous=json.loads((root/('installed-'+args.extra+'-result.json')).read_text())
            assert previous['status']=='passed-covered-checks';report['checks'].append(previous)
        if args.extra in ('maintenance','tor','vpn'):
            type_text('systemctl reboot\n')
            time.sleep(5)
            login()
            phase(args.extra+'-reboot')
    else:
        phase('configure')
        type_text('systemctl reboot\n')
        time.sleep(5)
        login()
        phase('reboot')
    if not args.keep_running: type_text('systemctl poweroff\n')
    report['status']='passed-'+args.extra if args.extra else 'passed-installed-reboot'
except Exception as exc:
    report.update(status='failed',error=repr(exc))
    raise
finally:
    (root/(args.extra+'-acceptance.json' if args.extra else 'boot-acceptance.json')).write_text(json.dumps(report,indent=2))
