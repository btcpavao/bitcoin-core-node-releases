#!/usr/bin/python3
"""Real Tor delivery to an owned, loopback-only regtest onion receiver.

Run only in the dedicated QEMU clone with the specified disposable NAT NIC.
No real coins, host networking changes, exit relay or public Bitcoin peers.
"""
import argparse,hashlib,json,os,pwd,shutil,socket,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('phase',choices=['tor','tor-reboot']);p.add_argument('--media',type=Path,required=True);a=p.parse_args()
assert os.geteuid()==0 and os.environ.get('NODE_VM_ACCEPTANCE')=='1'
assert socket.gethostname()=='node-fixture' and 'Q35' in Path('/sys/devices/virtual/dmi/id/product_name').read_text()
interfaces=[x for x in Path('/sys/class/net').iterdir() if x.name!='lo']
assert len(interfaces)==1 and interfaces[0].joinpath('address').read_text().strip()=='52:54:00:31:00:01'
assert (a.media/'NODE-TEST-ONLY').read_text().strip()=='disposable QEMU fixture'
sys.path.insert(0,'/usr/lib/bitcoin-core-node')
from rpc import CoreRPC
from wallets import WalletService
rpc=CoreRPC();saved=json.loads(Path('/etc/bitcoin-core-node/setup.json').read_text())
assert saved['network']=='regtest'
report={'phase':a.phase,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'covered':[]};child=None;root=Path('/run/node-tor-receiver');torrc=Path('/etc/tor/torrc');original=torrc.read_text()
def run(cmd,**kwargs):return subprocess.run(cmd,check=True,capture_output=True,text=True,timeout=150,**kwargs)
def wait(label,fn,seconds=240):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        try:
            result=fn()
            if result:return result
        except Exception:pass
        time.sleep(2)
    raise RuntimeError('Deadline: '+label)
def passed(s):report['covered'].append(s);print('PASS '+s,flush=True)
if a.phase=='tor-reboot':
    before=json.loads((a.media/'installed-tor-result.json').read_text())
    assert before['status']=='passed-covered-checks' and before['boot_id']!=report['boot_id']
    assert saved['profile']=='tor' and saved['private_broadcast'] is True
    assert Path('/etc/resolv.conf').resolve()==Path('/run/systemd/resolve/stub-resolv.conf')
    wait('Core Tor profile after actual reboot',lambda:any(n['name']=='onion' and n['reachable'] for n in rpc('getnetworkinfo')['networks']),60)
    assert all(not n['reachable'] for n in rpc('getnetworkinfo')['networks'] if n['name'] in ('ipv4','ipv6'))
    wait('Tor bootstrap after actual reboot',lambda:'Bootstrapped 100%' in run(['journalctl','-b','-u','tor@default.service','--no-pager']).stdout,300)
    passed('real reboot preserves Tor/privatebroadcast profile, resolver linkage, restricted Core networks and successful Tor bootstrap')
    report['status']='passed-covered-checks'
    (a.media/'installed-tor-reboot-result.json').write_text(json.dumps(report,indent=2)+'\n');os.sync();sys.exit(0)
try:
    if root.exists():
        with socket.socket() as check:check.bind(('127.0.0.1',19432))
        shutil.rmtree(root)
    root.mkdir(mode=0o700)
    executable=Path('/proc')/run(['systemctl','show','bitcoin-core-node','-p','MainPID','--value']).stdout.strip()/'exe'
    binary=executable.resolve()
    assert hashlib.sha256(binary.read_bytes()).hexdigest()=='580ac61190154da31aac3f82d13c4254ef453d70e1bf2c39d338dac5129c92ac'
    child=subprocess.Popen([str(binary),'-regtest','-datadir='+str(root),'-server=1','-rpcport=19432',
        '-bind=127.0.0.1:19444=onion','-listenonion=0','-connect=0','-dns=0','-dnsseed=0',
        '-fixedseeds=0','-discover=0','-natpmp=0','-dbcache=32','-disablewallet=1','-persistmempool=0'],
        stdin=subprocess.DEVNULL,stdout=open(root/'console.log','w'),stderr=subprocess.STDOUT)
    receiver=CoreRPC(root/'regtest/.cookie',19432)
    wait('receiver ready',lambda:receiver('getblockchaininfo')['chain']=='regtest',30)
    for height in range(1,rpc('getblockcount')+1):
        assert receiver('submitblock',rpc('getblock',rpc('getblockhash',height),0)) is None
    assert receiver('getbestblockhash')==rpc('getbestblockhash') and not receiver('getrawmempool')
    service=WalletService(rpc,Path('/root/node-exchange-public'))
    rows=service.records();assert len(rows)==1 and rows[0]['txid'] in rpc('getrawmempool')
    row=rows[0];assert receiver('testmempoolaccept',[row['raw']])[0]['allowed']
    directory=Path('/var/lib/tor/node-acceptance-service')
    directory.mkdir(mode=0o700,exist_ok=True);account=pwd.getpwnam('debian-tor');os.chown(directory,account.pw_uid,account.pw_gid)
    torrc.write_text(original+'\n# Disposable regtest receiver fixture\nHiddenServiceDir '+str(directory)+'\nHiddenServicePort 18444 127.0.0.1:19444\n')
    run(['systemctl','restart','tor@default.service'])
    wait('Tor bootstrap',lambda:'Bootstrapped 100%' in run(['journalctl','-u','tor@default.service','--since','-5 minutes','--no-pager']).stdout,300)
    onion=wait('onion service hostname',lambda:(directory/'hostname').read_text().strip(),30)
    assert onion.endswith('.onion') and len(onion)==62
    passed('installed Tor bootstraps on real network; owned regtest receiver is reachable only on loopback onion endpoint')
    # Reset only this owned clone's public mempool; keep the chain and signed intent.
    # The completed USB fixture had already broadcast the transaction ordinarily.
    rpc('unloadwallet','vault_exchange',False)
    run(['systemctl','stop','bitcoin-core-node.service'])
    Path('/var/lib/bitcoin-core-node/data/regtest/mempool.dat').unlink(missing_ok=True)
    setup={**saved,'profile':'tor','private_broadcast':True}
    run(['/usr/libexec/core-node-admin','configure'],input=json.dumps({'setup':setup}))
    wait('production service ready',lambda:rpc('getnetworkinfo'),30)
    info=rpc('getnetworkinfo')
    assert any(n['name']=='onion' and n['reachable'] and n['proxy']=='127.0.0.1:9050' for n in info['networks'])
    assert all(not n['reachable'] for n in info['networks'] if n['name'] in ('ipv4','ipv6'))
    assert rpc('getrawmempool')==[], 'Fixture origin mempool must start empty'
    added=rpc('addpeeraddress',onion,18444,True)
    assert added['success'] or any(p['address']==onion for p in rpc('getnodeaddresses'))
    # Broadcast the authorized signed transaction from a clean origin mempool.
    assert rpc('sendrawtransaction',row['raw'])==row['txid']
    assert row['txid'] not in rpc('getrawmempool'), 'Private submission used ordinary mempool'
    assert any(t['txid']==row['txid'] for t in rpc('getprivatebroadcastinfo')['transactions'])
    def delivered():
        for peer_info in rpc('getpeerinfo'):
            if peer_info['addr'].startswith(onion+':') and peer_info['connection_type']!='private-broadcast':
                rpc('disconnectnode','',peer_info['id'])
        return row['txid'] in receiver('getrawmempool')
    wait('private transaction delivered through real Tor',delivered,360)
    received=receiver('getrawtransaction',row['txid'])
    assert received==row['raw']
    def acknowledged():
        pending=[t for t in rpc('getprivatebroadcastinfo')['transactions'] if t['txid']==row['txid']]
        return pending and sum('received' in peer for peer in pending[0]['peers'])
    acknowledged_count=wait('private peer acknowledgement',acknowledged,120)
    report['txid']=row['txid'];report['private_peer_acknowledgements']=acknowledged_count
    report['received_raw_sha256']=hashlib.sha256(bytes.fromhex(received)).hexdigest()
    passed('production Tor/privatebroadcast profile delivers exact signed regtest transaction through real onion transport to independent Core receiver')
    rpc('loadwallet','vault_exchange',True)
    report['status']='passed-covered-checks'
except Exception as exc:
    report.update(status='failed',error=repr(exc))
    for method in ['getpeerinfo','getprivatebroadcastinfo','getnodeaddresses']:
        try:report[method]=rpc(method)
        except Exception:pass
    report['tor_log']=subprocess.run(['journalctl','-u','tor@default.service','-n','40','--no-pager'],capture_output=True,text=True).stdout
    raise
finally:
    if child is not None:
        try:receiver('stop')
        except Exception:child.terminate()
        child.wait(timeout=30)
    torrc.write_text(original)
    # Keep the tested profile until the controller's reboot check; fixture only.
    (a.media/'installed-tor-result.json').write_text(json.dumps(report,indent=2)+'\n')
    os.sync()
