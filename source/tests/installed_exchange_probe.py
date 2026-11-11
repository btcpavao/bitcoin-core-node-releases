#!/usr/bin/python3
"""Disposable regtest exchange between actual Node and NIC-free Vault guests.

Only public descriptors, public transaction intent and PSBTs cross USB. Signing
keys and the signing Core instance stay in the Vault's verified RAM workspace.
This is a test driver, not a replacement for either production application.
"""
import argparse
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import resource
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import quote

p=argparse.ArgumentParser()
p.add_argument('phase',choices=['export','create','sign','broadcast','cleanup'])
p.add_argument('--media',type=Path,required=True)
a=p.parse_args()
assert os.environ.get('NODE_VM_ACCEPTANCE')=='1'
assert 'Q35' in Path('/sys/devices/virtual/dmi/id/product_name').read_text()
assert sorted(x.name for x in Path('/sys/class/net').iterdir())==['lo']
assert (a.media/'NODE-TEST-ONLY').read_text().strip()=='disposable QEMU fixture'
os.umask(0o077)
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
report={'phase':a.phase,'covered':[]}
ram=Path('/run/core-vault/tmp/node-exchange')
phrase='Synthetic regtest fixture only 2026'

def passed(label):
    report['covered'].append(label)
    print('PASS '+label,flush=True)

def write(name,value):
    (a.media/name).write_text(json.dumps(value,indent=2)+'\n')

def read(name):return json.loads((a.media/name).read_text())

def rpc_vault(method,*params,wallet=None):
    state=json.loads((ram/'fixture.json').read_text())
    process=Path('/proc')/str(state['pid'])
    assert process.joinpath('exe').resolve()==Path('/usr/local/bin/bitcoin-qt')
    assert os.fsencode('-datadir='+str(ram/'node')) in process.joinpath('cmdline').read_bytes().split(b'\0')
    # Vault's public-export adapter uses the native CLI argument convention.
    params=[json.loads(v) if isinstance(v,str) and (v in ('false','true') or v.startswith('[')) else v for v in params]
    auth=base64.b64encode((ram/'rpc.cookie').read_bytes().strip()).decode()
    connection=http.client.HTTPConnection('127.0.0.1',state['port'],timeout=30)
    try:
        connection.request('POST','/' if wallet is None else '/wallet/'+quote(wallet,safe=''),
            json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}),
            {'Authorization':'Basic '+auth,'Content-Type':'application/json'})
        result=json.loads(connection.getresponse().read())
        assert not result.get('error'), 'Core RPC failed: '+method
        return result['result']
    finally:connection.close()

try:
    if a.phase in ('export','sign','cleanup'):
        assert os.getuid()==1000 and socket.gethostname()=='core-vault'
        sys.path.insert(0,'/usr/lib/core-vault')
        sys.path.insert(0,'/usr/lib/core-vault-backup')
        import runtime
        runtime.check_storage();runtime.check_core_mounts()
        core=Path('/usr/local/bin/bitcoin-qt')
        assert hashlib.sha256(core.read_bytes()).hexdigest()=='d43632a3e54dfb181ba045db2a5b1ec2396a1acdda010e3b6d07b2e21c69c183'
        if a.phase=='export':
            ram.mkdir(mode=0o700,exist_ok=False)
            assert runtime.mount_at(ram)['maj:min']==runtime.mount_at(runtime.ROOT,True)['maj:min']
            for name in ('node','wallets','home','tmp','runtime','config','cache','data','state'):
                (ram/name).mkdir(mode=0o700)
            authority=next(x for x in [Path('/run/lightdm/vault/xauthority'),Path('/home/vault/.Xauthority')] if x.is_file() and os.access(x,os.R_OK))
            assert authority.stat().st_uid in (0,1000) and not authority.stat().st_mode&0o022
            assert not authority.is_symlink() and Path('/tmp/.X11-unix/X0').is_socket()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','HOME':str(ram/'home'),
                'TMPDIR':str(ram/'tmp'),'XDG_RUNTIME_DIR':str(ram/'runtime'),
                'XDG_CONFIG_HOME':str(ram/'config'),'XDG_CACHE_HOME':str(ram/'cache'),
                'XDG_DATA_HOME':str(ram/'data'),'XDG_STATE_HOME':str(ram/'state'),
                'QT_QPA_PLATFORM':'xcb','DISPLAY':':0','XAUTHORITY':str(authority)}
            command=[str(core),'-regtest','-datadir='+str(ram/'node'),'-walletdir='+str(ram/'wallets'),
                '-rpccookiefile='+str(ram/'rpc.cookie'),'-server=1','-rpcport='+str(port),
                '-rpcbind=127.0.0.1','-networkactive=0','-maxconnections=0','-listen=0',
                '-listenonion=0','-dnsseed=0','-fixedseeds=0','-discover=0','-natpmp=0',
                '-walletbroadcast=0','-dbcache=32','-keypool=20','-splash=0','-min','-nodebuglogfile']
            process=subprocess.Popen(command,env=env,cwd=ram,stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            (ram/'fixture.json').write_text(json.dumps({'pid':process.pid,'port':port}))
            for _ in range(300):
                assert process.poll() is None,'Secondary Core exited before readiness'
                try:
                    assert rpc_vault('getblockchaininfo')['chain']=='regtest';break
                except Exception:time.sleep(.2)
            else:raise RuntimeError('Secondary Core readiness deadline')
            assert not rpc_vault('getnetworkinfo')['networkactive']
            rpc_vault('createwallet','vault-exchange',False,False,phrase)
            assert rpc_vault('getwalletinfo',wallet='vault-exchange')['unlocked_until']==0
            public=ram/'watch-only.dat'
            rpc_vault('exportwatchonlywallet',str(public),wallet='vault-exchange')
            shutil.copyfile(public,a.media/'watch-only.dat')
            assert (a.media/'watch-only.dat').read_bytes()==public.read_bytes()
            pairing=rpc_vault('listdescriptors',False,wallet='vault-exchange')['descriptors']
            rpc_vault('createwallet','fixture-recipient',False,False,phrase)
            recipient=rpc_vault('getnewaddress',wallet='fixture-recipient')
            write('intent.json',{'recipient':recipient,'amount':'1.00000000','fee_rate':'2',
                'pairing':pairing})
            passed('verified Vault RAM workspace and pinned native Core, offline with no network device')
            passed('installed Vault exports locked-wallet public descriptors onto removable USB')
        elif a.phase=='sign':
            assert not rpc_vault('getnetworkinfo')['networkactive']
            intent=read('intent.json');proposal=read('proposal.json')
            psbt=base64.b64encode((a.media/'unsigned.psbt').read_bytes()).decode()
            decoded=rpc_vault('decodepsbt',psbt)
            outputs=decoded['tx']['vout']
            recipients=[r for r in outputs if r['scriptPubKey'].get('address')==intent['recipient']]
            assert len(recipients)==1 and str(recipients[0]['value'])=='1.0'
            assert decoded['tx']==proposal['decoded_transaction']
            assert 0<float(decoded['fee'])<0.0001
            for row in outputs:
                address=row['scriptPubKey'].get('address')
                assert address==intent['recipient'] or rpc_vault('getaddressinfo',address,wallet='vault-exchange')['ismine']
            rpc_vault('walletpassphrase',phrase,60,wallet='vault-exchange')
            try:signed=rpc_vault('walletprocesspsbt',psbt,True,'ALL',True,False,wallet='vault-exchange')
            finally:rpc_vault('walletlock',wallet='vault-exchange')
            assert rpc_vault('finalizepsbt',signed['psbt'])['complete']
            assert rpc_vault('getwalletinfo',wallet='vault-exchange')['unlocked_until']==0
            (a.media/'signed.psbt').write_bytes(base64.b64decode(signed['psbt']))
            assert rpc_vault('getrawmempool')==[]
            passed('independent Vault review verifies recipient, amount, fee, every change output and transaction intent')
            passed('native Core signs PSBT in RAM, relocks signing wallet and exports signed PSBT without broadcast')
        else:
            state=json.loads((ram/'fixture.json').read_text())
            rpc_vault('stop')
            for _ in range(150):
                cmd=Path('/proc')/str(state['pid'])/'cmdline'
                if not cmd.exists() or not cmd.read_bytes():break
                time.sleep(.1)
            else:raise RuntimeError('Signing fixture did not stop')
            shutil.rmtree(ram)
            passed('signing Core stopped and disposable RAM wallet fixture removed')
    else:
        assert os.geteuid()==0 and socket.gethostname()=='node-fixture'
        assert Path('/etc/bitcoin-core-node/installed').is_file()
        sys.path.insert(0,'/usr/lib/bitcoin-core-node')
        from rpc import CoreRPC
        from wallets import WalletService,WalletError
        rpc=CoreRPC();service=WalletService(rpc,Path('/root/node-exchange-public'))
        assert rpc('getblockchaininfo')['chain']=='regtest'
        intent=read('intent.json')
        if a.phase=='create':
            rpc('restorewallet','vault_exchange',str(a.media/'watch-only.dat'),True)
            assert rpc('listdescriptors',False,wallet='vault_exchange')['descriptors']==intent['pairing']
            assert service.watch('vault_exchange')['private_keys_enabled'] is False
            funding=service.receive('vault_exchange','Actual Vault USB fixture','bech32')
            rpc('generatetoaddress',101,funding)
            rpc('syncwithvalidationinterfacequeue')
            row=service.create_transaction('vault_exchange',intent['recipient'],intent['amount'],intent['fee_rate'])
            service.export_psbt(row['id'],a.media/'unsigned.psbt')
            write('proposal.json',{'id':row['id'],'decoded_transaction':rpc('decodepsbt',row['psbt'])['tx']})
            assert rpc('getrawmempool')==[]
            passed('installed Node validates matching receiving/change addresses and imports private-key-disabled wallet')
            passed('native Core funds regtest proposal and production Node exports unsigned PSBT without broadcast')
        else:
            proposal=read('proposal.json')
            accepted=service.import_signed((a.media/'signed.psbt').read_bytes())
            assert accepted['id']==proposal['id'] and accepted['status']=='ready'
            assert rpc('getrawmempool')==[]
            try:service.broadcast(accepted['id'],'0'*64)
            except WalletError:pass
            else:raise AssertionError('Incorrect confirmation accepted')
            result=service.broadcast(accepted['id'],hashlib.sha256(bytes.fromhex(accepted['raw'])).hexdigest())
            assert result['txid'] in rpc('getrawmempool')
            report['txid']=result['txid']
            assert service.watch('vault_exchange')['private_keys_enabled'] is False
            passed('installed Node matches signed proposal, rejects incorrect confirmation and broadcasts only after exact approval')
    report['status']='passed-covered-checks'
except Exception as exc:
    # Avoid recording arbitrary Core payloads or private signing context.
    report.update(status='failed',error_type=type(exc).__name__)
    raise
finally:
    write('exchange-'+a.phase+'-result.json',report)
    os.sync()
