#!/usr/bin/python3
"""Observe and exercise native Calamares in an existing, owned blank QEMU VM.

No coordinates are guessed: clicks are derived from current screenshot OCR.
Only the single 48-GiB /dev/vda fixture may pass the disk confirmation gates.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
from PIL import Image, ImageChops, ImageDraw

parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--reboot',action='store_true');parser.add_argument('--resume',choices=['boot-menu','live-home','keyboard','disk-selected','users','users-filled','summary','final-consent','installing'],default='boot-menu');args=parser.parse_args()
root=args.root.absolute();probe=Path(__file__).with_name('vm_probe.py')
assert root.is_relative_to(Path.home()/'node-v1-validation') and not root.is_symlink()
record=json.loads((root/'fixture.json').read_text());command=record['command']
assert command[command.index('-nic')+1]=='none' and str(root/'disk.qcow2') in ' '.join(command)
assert not record.get('usb') and '-cdrom' in command
report={'phase':'native-installer','source_iso':record['iso'],'screens':[]}

def call(action,*options):
    result=subprocess.run(['python3',str(probe),action,'--root',str(root),*options],capture_output=True,text=True,check=True,timeout=45)
    return result.stdout.strip()

def words():
    image=Path(call('screen'))
    scaled=root/'ocr-current-3x.png'
    with Image.open(image) as frame:frame.resize((frame.width*3,frame.height*3)).save(scaled)
    output=subprocess.run(['tesseract',str(scaled),'stdout','-l','eng','--psm','11','tsv'],capture_output=True,text=True,check=True,timeout=30).stdout
    rows=[]
    for line in output.splitlines()[1:]:
        fields=line.split('\t')
        if len(fields)==12 and fields[11].strip():rows.append((fields[11],*[int(value)//3 for value in fields[6:10]]))
    with Image.open(image) as frame:
        top=int(frame.height*.9)
        footer=root/'ocr-footer.png'
        frame.crop((0,top,frame.width,frame.height)).resize((frame.width*3,(frame.height-top)*3)).save(footer)
    output=subprocess.run(['tesseract',str(footer),'stdout','-l','eng','--psm','6','tsv'],capture_output=True,text=True,check=True,timeout=30).stdout
    rows=[row for row in rows if row[2]<top]
    for line in output.splitlines()[1:]:
        fields=line.split('\t')
        if len(fields)==12 and fields[11].strip():
            x,y,w,h=[int(value)//3 for value in fields[6:10]]
            rows.append((fields[11],x,y+top,w,h))
    # Mixed black-page/white-button polarity makes sparse OCR skip the primary
    # action. Detect its actual bright connected surface, then OCR that crop.
    with Image.open(image) as frame:
        mask=frame.convert('L').point(lambda value:255 if value>235 else 0)
        # The native confirmation uses a dark button with an orange focus
        # outline. Include that connected outline so its text is OCR'd in
        # isolation, just like the white primary actions below.
        red,green,blue=frame.convert('RGB').split()
        focus=ImageChops.multiply(red.point(lambda v:255 if v>200 else 0),
                                 green.point(lambda v:255 if 90<v<210 else 0))
        focus=ImageChops.multiply(focus,blue.point(lambda v:255 if v<80 else 0))
        mask=ImageChops.lighter(mask,focus)
        for _ in range(8):
            found=None
            data=mask.tobytes()
            for y in range(frame.height//2,frame.height,2):
                match=re.search(b'\xff{80,}',data[y*frame.width:(y+1)*frame.width])
                if match:
                    found=(match.start(),y);break
            if found is None:break
            before=mask.copy();ImageDraw.floodfill(mask,found,128,thresh=0)
            box=ImageChops.difference(before,mask).getbbox()
            if not box or box[2]-box[0]<80 or box[3]-box[1]<20:continue
            x1,y1,x2,y2=box
            crop=root/'ocr-primary-button.png'
            frame.crop(box).resize(((x2-x1)*3,(y2-y1)*3)).save(crop)
            output=subprocess.run(['tesseract',str(crop),'stdout','-l','eng','--psm','6','tsv'],
                                  capture_output=True,text=True,check=True,timeout=30).stdout
            parsed=[]
            for line in output.splitlines()[1:]:
                fields=line.split('\t')
                if len(fields)==12 and fields[11].strip():
                    x,y,w,h=[int(value)//3 for value in fields[6:10]]
                    parsed.append((fields[11],x+x1,y+y1,w,h))
            if parsed:
                rows=[row for row in rows if not (x1<=row[1]<x2 and y1<=row[2]<y2)]
                rows.extend(parsed)
    return image,rows,' '.join(row[0] for row in rows)

def wait(label,predicate,timeout=120):
    until=time.monotonic()+timeout;heartbeat=0
    while time.monotonic()<until:
        image,rows,text=words()
        if 'installation failed' in text.lower():raise RuntimeError('Native installer failed: '+text)
        if predicate(text.lower()):
            report['screens'].append({'label':label,'image':str(image),'text':text})
            print(json.dumps({'observed':label,'image':str(image)}),flush=True)
            return image,rows,text
        if time.monotonic()>heartbeat:
            print('Waiting for observed '+label,flush=True);heartbeat=time.monotonic()+30
        time.sleep(3)
    raise RuntimeError('Screen deadline exceeded: '+label)

def click(phrase,observation,bottom=False):
    image,rows,_=observation
    def clean(s):return re.sub(r'^[^a-z0-9]+|[^a-z0-9]+$','',s.lower())
    expected=[clean(word) for word in phrase.split()];matches=[]
    height=Image.open(image).height
    for index in range(len(rows)-len(expected)+1):
        selected=rows[index:index+len(expected)]
        if [clean(row[0]) for row in selected]!=expected:continue
        if max(row[2] for row in selected)-min(row[2] for row in selected)>max(row[4] for row in selected):continue
        if bottom and min(row[2] for row in selected)<height*.8:continue
        matches.append(selected)
    if len(matches)!=1:raise RuntimeError('Expected one observed control: '+phrase+'; found '+str(len(matches)))
    selected=matches[0];x=min(r[1] for r in selected);y=min(r[2] for r in selected)
    right=max(r[1]+r[3] for r in selected);low=max(r[2]+r[4] for r in selected)
    call('click','--point',str((x+right)//2)+','+str((y+low)//2),'--observed',str(image))
    time.sleep(.8)

def disk_gate(text,require_size=True):
    compact=text.lower().replace(' ','')
    assert '/dev/vda' in compact,text
    assert not require_size or (re.search(r'48(?:\.0+)?gib',compact) or ('49151mib' in compact and not record['uefi']) or ('48637mib' in compact and '512mib' in compact and record['uefi'])),text
    assert not re.search(r'/dev/(?:sd[a-z]|hd[a-z]|nvme|vd[b-z])',compact),text

try:
    if args.resume=='boot-menu':
        wait('boot-menu',lambda s:'live system' in s or ('boot menu' in s and 'utilities' in s))
        call('key','--keys','ret')
    if args.resume in ('boot-menu','live-home','keyboard'):
        keyboard=wait('keyboard',lambda s:'choose your keyboard layout' in s and 'english' in s and 'continue' in s)
        click('Continue',keyboard)
    if args.resume not in ('summary','final-consent','installing'):
        disk=wait('disk-selected',lambda s:'installation drive' in s and '/dev/vda' in s and 'continue' in s)
        disk_gate(disk[2]);click('Continue',disk)
    if args.resume not in ('final-consent','installing'):
        summary=wait('summary',lambda s:'ready to install' in s and 'understand that everything' in s )
        disk_gate(summary[2],False)
        click('understand',summary)
        consent=wait('erase-acknowledgement',lambda s:'ready to install' in s and 'understand that everything' in s)
        disk_gate(consent[2],False)
        click('Erase drive and install',consent)
    if args.resume != 'installing':
        consent=wait('final-consent',lambda s:'installer is about to make changes' in s and 'undo these changes' in s)
        click('Install now',consent)
    wait('installation-branding',lambda s:'installing bitcoin core node' in s and 'powered by debian' in s,120)
    finished=wait('finished',lambda s:'bitcoin core node is ready' in s and 'restart into bitcoin core node' in s,900)
    report['status']='installed-awaiting-normal-reboot'
    if args.reboot:
        click('Restart into Bitcoin Core Node',finished)
        until=time.monotonic()+180;handled_eject=False
        while time.monotonic()<until:
            image,rows,text=words();lower=text.lower()
            if 'watch-only wallets' in lower and 'node settings' in lower:
                report['screens'].append({'label':'home-after-native-installer-reboot','image':str(image),'text':text})
                report['status']='installed-and-rebooted-through-native-finish'
                print(json.dumps({'observed':'home-after-native-installer-reboot','image':str(image)}),flush=True)
                break
            if not handled_eject and ('remove' in lower and ('medium' in lower or 'media' in lower)) and ('enter' in lower or 'return' in lower):
                report['screens'].append({'label':'live-medium-removal-prompt','image':str(image),'text':text})
                # Only this owned virtual CD is affected by the guest's eject request.
                call('key','--keys','ret');handled_eject=True
            time.sleep(2)
        else:raise RuntimeError('Native installer restart did not reach the installed Home.')
except Exception as exc:
    report.update(status='failed',error=repr(exc));raise
finally:
    (root/'installer-result.json').write_text(json.dumps(report,indent=2))
