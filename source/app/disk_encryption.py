"""Read-only status of the installed system disk's encryption."""
import json
import subprocess
from pathlib import Path


def status():
    if 'boot=live' in Path('/proc/cmdline').read_text().split():
        return 'live'
    source=subprocess.run(['/usr/bin/findmnt','-n','-o','SOURCE','/'],check=True,
                          capture_output=True,text=True,timeout=10).stdout.strip().split('[',1)[0]
    result=subprocess.run(['/usr/bin/lsblk','-J','-s','-p','-o','NAME,TYPE,FSTYPE',source],
                          check=True,capture_output=True,text=True,timeout=10)
    def encrypted(rows):
        return any(row.get('type')=='crypt' or row.get('fstype')=='crypto_LUKS' or encrypted(row.get('children',[])) for row in rows)
    return 'encrypted' if encrypted(json.loads(result.stdout)['blockdevices']) else 'plain'
