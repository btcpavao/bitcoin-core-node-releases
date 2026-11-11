#!/usr/bin/python3
"""Exercise signed maintenance activation on the disposable installed Node."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

parser=argparse.ArgumentParser()
parser.add_argument('phase',choices=['maintenance','maintenance-reboot'])
parser.add_argument('--media',type=Path,required=True)
args=parser.parse_args()
assert os.geteuid()==0 and os.environ.get('NODE_VM_ACCEPTANCE')=='1'
assert 'Q35' in Path('/sys/devices/virtual/dmi/id/product_name').read_text()
assert socket.gethostname()=='node-fixture'
assert sorted(p.name for p in Path('/sys/class/net').iterdir())==['lo']
assert 'boot=live' not in Path('/proc/cmdline').read_text().split()
assert (args.media/'NODE-TEST-ONLY').read_text().strip()=='disposable QEMU fixture'
assert Path('/etc/bitcoin-core-node/installed').is_file()
sys.path.insert(0,'/usr/lib/bitcoin-core-node')
from rpc import CoreRPC
from upgrades import active_release,inspect_bundle

report={'phase':args.phase,'covered':[], 'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
record_path=Path('/var/lib/bitcoin-core-node/maintenance-acceptance.json')
rpc=CoreRPC()
def passed(s):report['covered'].append(s);print('PASS '+s,flush=True)

try:
    before=rpc('getblockchaininfo')
    assert before['chain']=='regtest' and before['blocks']==101
    assert rpc('getwalletinfo',wallet='vmwatch')['private_keys_enabled'] is False
    if args.phase=='maintenance':
        bundle=args.media/'bundle'
        current=active_release()
        verified=inspect_bundle(bundle,'32.1')
        request={'directory':str(bundle),'version':'32.1','archive_sha256':verified['archive_sha256'],'current_sha256':current['binary_sha256']}
        output=subprocess.run(['/usr/libexec/core-node-admin','core-update'],input=json.dumps(request),
            capture_output=True,text=True,check=True,timeout=360)
        result=json.loads(output.stdout);assert result['ok'] is True
        selected=active_release()
        assert selected['path']!=current['path'] and len(selected['signers'])>=2
        assert hashlib.sha256((Path(selected['path'])/'bin/bitcoind').read_bytes()).hexdigest()==selected['binary_sha256']
        assert (Path(current['path'])/'bin/bitcoind').is_file()
        assert (Path(result['backup'])/'wallets/vmwatch/wallet.dat').is_file()
        assert (Path(result['backup'])/'previous-core.json').is_file()
        report.update(selected=selected['path'],binary_sha256=selected['binary_sha256'],tip=before['bestblockhash'],backup=result['backup'])
        passed('genuine signed Core 32.1 maintenance reactivation stops cleanly and selects independently verified bytes')
        passed('previous Core binaries, consistent wallet database snapshot and previous provenance are retained')
        assert rpc('getbestblockhash')==before['bestblockhash'] and 'vmwatch' in rpc('listwallets')
        passed('activated installed service retains loaded watch-only wallet and chain tip')
        record_path.write_text(json.dumps(report,indent=2))
    else:
        previous=json.loads(record_path.read_text())
        assert report['boot_id']!=previous['boot_id']
        selected=active_release()
        assert selected['path']==previous['selected']
        assert selected['binary_sha256']==previous['binary_sha256']
        pid=subprocess.check_output(['systemctl','show','bitcoin-core-node.service','--property=MainPID','--value'],text=True).strip()
        assert Path('/proc',pid,'exe').resolve()==Path(selected['path'])/'bin/bitcoind'
        assert rpc('getbestblockhash')==previous['tip'] and 'vmwatch' in rpc('listwallets')
        passed('real reboot runs selected signed maintenance executable and preserves the loaded wallet and chain tip')
    report['status']='passed-covered-checks'
except Exception as exc:
    report.update(status='failed',error=repr(exc));raise
finally:
    (args.media/('installed-'+args.phase+'-result.json')).write_text(json.dumps(report,indent=2)+'\n')
    os.sync()
