#!/usr/bin/python3
"""Real pinned Core configuration and persisted-wallet restart checks.

P2P is explicitly disabled in this contract test. Actual routing/leakage tests
are a separate gate. Only a disposable private-key-disabled wallet is created.
"""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from state import DATA,CORE_SHA256,core_arguments
from network import core_config
from rpc import CoreRPC

parser=argparse.ArgumentParser();parser.add_argument('--core-bin',type=Path,required=True);args=parser.parse_args()
with (args.core_bin/'bitcoind').open('rb') as stream:
    assert hashlib.file_digest(stream,'sha256').hexdigest()==CORE_SHA256
for profile,private in [('clearnet',False),('tor',False),('wireguard',False),('clearnet',True)]:
    with tempfile.TemporaryDirectory(prefix='node-profile-') as temporary:
        root=Path(temporary);data=root/'data';data.mkdir();(data/'wallets').mkdir()
        conf=data/'bitcoin.conf';cookie=root/'cookie'
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        setup={'version':1,'confirmed':True,'profile':profile,'network':'regtest','prune_mib':0,'data_uuid':None,'private_broadcast':private}
        # Production seeds an editable managed datadir config before launching.
        # Network policy is already supplied by core_arguments; do not duplicate
        # list-valued network options in this disposable fixture's config.
        conf.write_text('# Additional Bitcoin Core options.\n')
        flags=[flag.replace(str(DATA),str(data))
               .replace('/run/bitcoin-core-node/auth.cookie',str(cookie))
               for flag in core_arguments(setup) if not flag.startswith('-rpcport=')]
        flags+=['-rpcport='+str(port),'-networkactive=0','-dbcache=32','-printtoconsole=1','-debuglogfile=0']
        rpc=CoreRPC(cookie,port)
        for iteration in range(2):
            with (root/'startup.txt').open('w') as log:
                process=subprocess.Popen([str(args.core_bin/'bitcoind'),*flags],stdout=log,stderr=log)
                try:
                    for _ in range(200):
                        if process.poll() is not None:
                            raise RuntimeError('Core configuration rejected: '+(root/'startup.txt').read_text()[-4000:])
                        try:info=rpc('getnetworkinfo');break
                        except Exception:time.sleep(.1)
                    else:raise RuntimeError('Core did not start.')
                    assert info['version']==320100 and info['networkactive'] is False
                    if iteration==0:
                        rpc('createwallet','watch',True,True,'',False,True,True)
                    assert 'watch' in rpc('listwallets')
                    assert rpc('getwalletinfo',wallet='watch')['private_keys_enabled'] is False
                    if profile=='tor' or private:
                        onion=next(n for n in info['networks'] if n['name']=='onion')
                        assert onion['proxy']=='127.0.0.1:9050'
                    rpc('stop');process.wait(timeout=30)
                finally:
                    if process.poll() is None:process.terminate();process.wait(timeout=30)
        print('PASS pinned Core config and wallet persistence:',profile,'private_broadcast='+str(private))
print('Not established by this test: packet privacy, installed service lifetime, disk mount policy, or private broadcast delivery.')
