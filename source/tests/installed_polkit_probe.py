#!/usr/bin/python3
"""Invoke the installed narrow snapshot helper as the real desktop account."""
import base64,hashlib,json,os,socket,sys
from pathlib import Path
assert os.getuid()==1000 and socket.gethostname()=='node-fixture'
assert 'Q35' in Path('/sys/devices/virtual/dmi/id/product_name').read_text()
assert Path('/etc/bitcoin-core-node/installed').is_file()
sys.path.insert(0,'/usr/lib/bitcoin-core-node')
from ui import admin
from rpc import CoreRPC
rpc=CoreRPC(); assert rpc('getblockchaininfo')['chain']=='regtest'
assert rpc('getwalletinfo',wallet='vmwatch')['private_keys_enabled'] is False
snapshot=admin('wallet-snapshot',{'wallet':'vmwatch'})
data=base64.b64decode(snapshot['data'],validate=True)
assert data.startswith(b'SQLite format 3\0') and hashlib.sha256(data).hexdigest()==snapshot['sha256']
result={'status':'passed-covered-checks','uid':os.getuid(),'covered':['installed desktop account invokes production pkexec helper after native polkit authentication','consistent watch-only SQLite snapshot returned with verified checksum'],'snapshot_bytes':len(data),'sha256':snapshot['sha256']}
Path('/home/nodecheck/polkit-result.json').write_text(json.dumps(result,indent=2)+'\n')
print('POLKIT_SNAPSHOT_PASSED',flush=True)
