#!/usr/bin/python3
"""Persist a disposable WireGuard profile and verify its actual installed boot."""
import argparse,ast,json,os,pwd,select,socket,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('phase',choices=['vpn','vpn-reboot']);p.add_argument('--media',type=Path,required=True);a=p.parse_args()
assert os.geteuid()==0 and os.environ.get('NODE_VM_ACCEPTANCE')=='1'
assert socket.gethostname()=='node-fixture' and 'Q35' in Path('/sys/devices/virtual/dmi/id/product_name').read_text()
assert set(p.name for p in Path('/sys/class/net').iterdir())<=({'lo'} if a.phase=='vpn' else {'lo','core-node'})
assert Path('/etc/bitcoin-core-node/installed').is_file()
assert (a.media/'NODE-TEST-ONLY').read_text().strip()=='disposable QEMU fixture'
sys.path.insert(0,'/usr/lib/bitcoin-core-node')
from rpc import CoreRPC
rpc=CoreRPC();statefile=Path('/root/node-vpn-boot-fixture.json');server=None;peer_name='node-acceptance-provider'
report={'phase':a.phase,'covered':[],'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
def run(cmd,**kwargs):return subprocess.run(cmd,check=True,capture_output=True,text=True,timeout=150,**kwargs)
def peer(*cmd,**kwargs):return run(['ip','netns','exec',peer_name,*cmd],**kwargs)
def passed(s):report['covered'].append(s);print('PASS '+s,flush=True)
def ready():
    for _ in range(200):
        try:return rpc('getnetworkinfo')
        except Exception:time.sleep(.1)
    raise RuntimeError('Core not ready')
def configure(setup,wireguard=None):
    body={'setup':setup}
    if wireguard:body['wireguard']=wireguard
    run(['/usr/libexec/core-node-admin','configure'],input=json.dumps(body));ready()
try:
    setup=json.loads(Path('/etc/bitcoin-core-node/setup.json').read_text());assert setup['network']=='regtest'
    if a.phase=='vpn':
        assert setup['profile']=='clearnet' and not statefile.exists()
        private=run(['wg','genkey']).stdout.strip();provider=run(['wg','genkey']).stdout.strip()
        public=run(['wg','pubkey'],input=private+'\n').stdout.strip();provider_public=run(['wg','pubkey'],input=provider+'\n').stdout.strip()
        state={'setup':setup,'provider_private':provider,'client_public':public,'boot_id':report['boot_id'],'tip':rpc('getbestblockhash')}
        with statefile.open('x') as f:os.fchmod(f.fileno(),0o600);json.dump(state,f)
        tunnel='[Interface]\nPrivateKey = '+private+'\nAddress = 172.31.0.1/30\nDNS = 172.31.0.2\n\n[Peer]\nPublicKey = '+provider_public+'\nAllowedIPs = 0.0.0.0/0\nEndpoint = 192.0.2.2:51820\n'
        configure({**setup,'profile':'wireguard'},tunnel)
        passed('production WireGuard profile persists with unavailable disposable provider and fail-closed policy')
    else:
        state=json.loads(statefile.read_text())
        assert state['boot_id']!=report['boot_id'] and setup['profile']=='wireguard'
        assert Path('/sys/class/net/core-node').exists()
        assert Path('/etc/resolv.conf').resolve()==Path('/run/systemd/resolve/stub-resolv.conf')
        ready();assert rpc('getbestblockhash')==state['tip']
        # Reuse only the literal UDP/DNS fixtures, without running the other test.
        tree=ast.parse((a.media/'installed_network_probe.py').read_text())
        literals={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('SERVER','SEND')}
        uid=pwd.getpwnam('bitcoinnode').pw_uid
        def reaches(ip,as_uid=uid):return run(['python3','-c',literals['SEND'],ip,'19444',str(as_uid)]).stdout.strip()=='True'
        run(['ip','netns','add',peer_name]);run(['ip','link','add','node-uplink','type','veth','peer','name','provider'])
        run(['ip','link','set','provider','netns',peer_name]);peer('ip','addr','add','192.0.2.2/24','dev','provider')
        peer('ip','-6','addr','add','2001:db8:42::2/64','dev','provider','nodad');peer('ip','link','set','provider','up');peer('ip','link','set','lo','up')
        run(['nmcli','device','set','node-uplink','managed','yes'])
        run(['nmcli','connection','add','type','ethernet','ifname','node-uplink','con-name','node-acceptance-uplink','ipv4.method','manual','ipv4.addresses','192.0.2.1/24','ipv4.gateway','192.0.2.2','ipv4.dns','192.0.2.2','ipv6.method','manual','ipv6.addresses','2001:db8:42::1/64','ipv6.gateway','2001:db8:42::2'])
        run(['nmcli','connection','up','node-acceptance-uplink'])
        dnslog=Path('/run/node-vpn-boot-dns.jsonl')
        server=subprocess.Popen(['ip','netns','exec',peer_name,'python3','-u','-c',literals['SERVER'],str(dnslog)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        assert select.select([server.stdout],[],[],10)[0] and server.stdout.readline().strip()=='READY'
        assert not reaches('192.0.2.2') and not reaches('2001:db8:42::2') and not reaches('192.0.2.2',0)
        passed('actual reboot restores VPN interface, policy and resolver; unavailable provider allows no daemon or OS direct fallback')
        keyfile=Path('/run/node-vpn-provider-key');keyfile.write_text(state['provider_private']+'\n');keyfile.chmod(0o600)
        peer('ip','link','add','provider-wg','type','wireguard')
        peer('wg','set','provider-wg','private-key',str(keyfile),'listen-port','51820','peer',state['client_public'],'allowed-ips','172.31.0.1/32')
        peer('ip','addr','add','172.31.0.2/30','dev','provider-wg');peer('ip','link','set','provider-wg','up')
        for _ in range(15):
            if reaches('172.31.0.2'):break
            time.sleep(1)
        else:raise RuntimeError('Restored WireGuard handshake failed')
        run(['resolvectl','flush-caches'])
        assert '203.0.113.9' in run(['getent','ahostsv4','reboot-vpn-fixture.example.org']).stdout
        queries=[json.loads(row) for row in dnslog.read_text().splitlines()]
        assert queries and all(row['source']=='172.31.0.1' for row in queries)
        assert not reaches('192.0.2.2') and not reaches('2001:db8:42::2')
        passed('restored installed VPN completes genuine handshake and glibc DNS through tunnel without direct IPv4/IPv6 escape')
        configure(state['setup']);assert rpc('getbestblockhash')==state['tip'];statefile.unlink()
        passed('explicit clearnet restoration retains exact wallet and chain state after VPN boot')
    report['status']='passed-covered-checks'
except Exception as exc:
    report.update(status='failed',error=repr(exc));raise
finally:
    if server is not None:
        server.terminate();server.wait(timeout=10)
        subprocess.run(['nmcli','connection','delete','node-acceptance-uplink'],capture_output=True)
        subprocess.run(['ip','link','delete','node-uplink'],capture_output=True)
        subprocess.run(['ip','netns','delete',peer_name],capture_output=True)
        Path('/run/node-vpn-provider-key').unlink(missing_ok=True)
    (a.media/('installed-'+a.phase+'-result.json')).write_text(json.dumps(report,indent=2)+'\n');os.sync()
