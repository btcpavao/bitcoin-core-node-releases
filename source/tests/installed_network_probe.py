#!/usr/bin/python3
"""Run only in the dedicated, installed, NIC-free node-fixture QEMU guest."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import pwd
import select
import socket
import subprocess
import sys
import tempfile
import time

parser=argparse.ArgumentParser()
parser.add_argument('phase',choices=['network'])
parser.add_argument('--media',type=Path,required=True)
args=parser.parse_args()
assert os.geteuid()==0 and os.environ.get('NODE_VM_ACCEPTANCE')=='1'
assert 'Q35' in Path('/sys/devices/virtual/dmi/id/product_name').read_text()
assert socket.gethostname()=='node-fixture'
assert sorted(p.name for p in Path('/sys/class/net').iterdir())==['lo']
assert 'boot=live' not in Path('/proc/cmdline').read_text().split()
assert Path('/etc/bitcoin-core-node/installed').is_file()
assert (args.media/'NODE-TEST-ONLY').read_text().strip()=='disposable QEMU fixture'
sys.path.insert(0,'/usr/lib/bitcoin-core-node')
from rpc import CoreRPC

report={'phase':'network','covered':[]}
peer_name='node-acceptance-provider'
uid=pwd.getpwnam('bitcoinnode').pw_uid
saved=json.loads(Path('/etc/bitcoin-core-node/setup.json').read_text())
assert saved['network']=='regtest' and saved['profile']=='clearnet'
server=None

def run(cmd,**kwargs):
    return subprocess.run(cmd,check=True,capture_output=True,text=True,timeout=150,**kwargs)
def peer(*cmd,**kwargs):return run(['ip','netns','exec',peer_name,*cmd],**kwargs)
def passed(s):report['covered'].append(s);print('PASS '+s,flush=True)
def configure(profile,tunnel=None):
    setup={**saved,'profile':profile,'private_broadcast':False}
    request={'setup':setup}
    if tunnel:request['wireguard']=tunnel
    result=run(['/usr/libexec/core-node-admin','configure'],input=json.dumps(request))
    rpc=CoreRPC()
    for _ in range(200):
        try:
            rpc('getnetworkinfo');return rpc
        except Exception:time.sleep(.1)
    raise RuntimeError('Installed Core not ready after profile switch.')

SEND='''import socket,sys,os
os.setgid(int(sys.argv[3]));os.setuid(int(sys.argv[3]))
s=socket.socket(socket.AF_INET6 if ':' in sys.argv[1] else socket.AF_INET,socket.SOCK_DGRAM)
s.settimeout(1)
try:
 s.sendto(b'node-probe',(sys.argv[1],int(sys.argv[2])))
 print(s.recvfrom(128)[0]==b'node-probe')
except OSError:print(False)
'''
def reaches(address,port=19444,as_uid=uid):
    return run(['python3','-c',SEND,address,str(port),str(as_uid)]).stdout.strip()=='True'

SERVER='''import socket,select,struct,json,sys
sockets=[]
for af,host,port in [(socket.AF_INET,'0.0.0.0',19444),(socket.AF_INET,'0.0.0.0',53),(socket.AF_INET6,'::',19444)]:
 s=socket.socket(af,socket.SOCK_DGRAM)
 if af==socket.AF_INET6:s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
 s.bind((host,port));sockets.append(s)
print('READY',flush=True)
while True:
 for s in select.select(sockets,[],[])[0]:
  data,source=s.recvfrom(4096)
  if s.getsockname()[1]!=53:
   s.sendto(data,source);continue
  if len(data)<12:continue
  end=12
  try:
   while data[end]:end+=data[end]+1
   end+=1;qtype,qclass=struct.unpack('!HH',data[end:end+4]);end+=4
   question=data[12:end]
   answer=b''
   if qtype==1:answer=b'\\xc0\\x0c'+struct.pack('!HHIH',1,1,1,4)+socket.inet_aton('203.0.113.9')
   response=data[:2]+struct.pack('!HHHHH',0x8180,1,int(bool(answer)),0,0)+question+answer
   with open(sys.argv[1],'a') as log:log.write(json.dumps({'source':source[0],'type':qtype})+'\\n')
   s.sendto(response,source)
  except (IndexError,ValueError,struct.error):pass
'''

try:
    run(['ip','netns','add',peer_name])
    run(['ip','link','add','node-uplink','type','veth','peer','name','provider'])
    run(['ip','link','set','provider','netns',peer_name])
    peer('ip','addr','add','192.0.2.2/24','dev','provider')
    peer('ip','-6','addr','add','2001:db8:42::2/64','dev','provider','nodad')
    peer('ip','link','set','provider','up');peer('ip','link','set','lo','up')
    run(['nmcli','device','set','node-uplink','managed','yes'])
    run(['nmcli','connection','add','type','ethernet','ifname','node-uplink','con-name','node-acceptance-uplink',
        'ipv4.method','manual','ipv4.addresses','192.0.2.1/24','ipv4.gateway','192.0.2.2','ipv4.dns','192.0.2.2',
        'ipv6.method','manual','ipv6.addresses','2001:db8:42::1/64','ipv6.gateway','2001:db8:42::2'])
    run(['nmcli','connection','up','node-acceptance-uplink'])
    with tempfile.TemporaryDirectory(prefix='node-network-',dir='/run') as folder:
        root=Path(folder);dnslog=root/'dns.jsonl'
        server=subprocess.Popen(['ip','netns','exec',peer_name,'python3','-u','-c',SERVER,str(dnslog)],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        assert select.select([server.stdout],[],[],10)[0] and server.stdout.readline().strip()=='READY'
        rpc=configure('clearnet')
        # NetworkManager activation can precede IPv6 duplicate-address detection.
        for attempt in range(15):
            ipv4,ipv6=reaches('192.0.2.2'),reaches('2001:db8:42::2')
            if ipv4 and ipv6:break
            time.sleep(1)
        assert ipv4 and ipv6, {'ipv4':ipv4,'ipv6':ipv6}
        assert rpc('getblockcount')==101
        passed('installed NetworkManager uplink and clearnet IPv4/IPv6 connectivity')
        configure('tor')
        assert not reaches('192.0.2.2') and not reaches('2001:db8:42::2')
        assert not reaches('192.0.2.2',53)
        assert reaches('192.0.2.2',as_uid=0)
        run(['systemctl','stop','tor@default.service'])
        assert not reaches('192.0.2.2') and not reaches('2001:db8:42::2')
        passed('installed Tor profile and stopped-Tor failure block daemon direct/DNS/IPv6 egress; OS scope remains distinct')
        private=run(['wg','genkey']).stdout.strip(); provider_private=run(['wg','genkey']).stdout.strip()
        public=run(['wg','pubkey'],input=private+'\n').stdout.strip()
        provider_public=run(['wg','pubkey'],input=provider_private+'\n').stdout.strip()
        keyfile=root/'provider-key';keyfile.write_text(provider_private+'\n');keyfile.chmod(0o600)
        peer('ip','link','add','provider-wg','type','wireguard')
        peer('wg','set','provider-wg','private-key',str(keyfile),'listen-port','51820','peer',public,'allowed-ips','172.31.0.1/32')
        peer('ip','addr','add','172.31.0.2/30','dev','provider-wg');peer('ip','link','set','provider-wg','up')
        tunnel='[Interface]\nPrivateKey = '+private+'\nAddress = 172.31.0.1/30\nDNS = 172.31.0.2\n\n[Peer]\nPublicKey = '+provider_public+'\nAllowedIPs = 0.0.0.0/0\nEndpoint = 192.0.2.2:51820\n'
        configure('wireguard',tunnel)
        assert reaches('172.31.0.2')
        assert not reaches('192.0.2.2') and not reaches('192.0.2.2',53) and not reaches('2001:db8:42::2')
        assert not reaches('192.0.2.2',as_uid=0)
        passed('installed administrator, wg-quick, real handshake and full-tunnel firewall')
        run(['resolvectl','flush-caches'])
        before=dnslog.read_text() if dnslog.exists() else ''
        resolved=run(['getent','ahostsv4','node-vpn-fixture.example.org']).stdout
        assert '203.0.113.9' in resolved
        queries=[json.loads(line) for line in dnslog.read_text()[len(before):].splitlines()]
        assert queries and all(item['source']=='172.31.0.1' for item in queries),queries
        report['resolved_status']=run(['resolvectl','status']).stdout
        passed('actual glibc/systemd-resolved DNS request traverses WireGuard and avoids uplink DNS')
        peer('ip','link','set','provider-wg','down')
        assert not reaches('172.31.0.2') and not reaches('192.0.2.2') and not reaches('2001:db8:42::2')
        passed('provider failure has no direct fallback while physical routes remain available')
        run(['ip','link','delete','core-node'])
        assert not reaches('192.0.2.2') and not reaches('2001:db8:42::2') and not reaches('192.0.2.2',53)
        passed('tunnel removal preserves installed whole-device kill switch')
        configure('clearnet')
        assert reaches('192.0.2.2')
        assert CoreRPC()('getblockcount')==101
        passed('explicit return to clearnet restores connection without losing wallet/chain data')
    report['status']='passed-covered-checks'
except Exception as exc:
    report.update(status='failed',error=repr(exc))
    report['diagnostics']={}
    for label,command in [('addresses',['ip','addr']),('routes',['ip','route']),('ipv6_routes',['ip','-6','route']),('policy',['nft','list','ruleset']),('resolver',['resolvectl','status'])]:
        result=subprocess.run(command,capture_output=True,text=True,timeout=10)
        report['diagnostics'][label]=result.stdout+result.stderr
    raise
finally:
    if server is not None:server.terminate();server.wait(timeout=10)
    subprocess.run(['nmcli','connection','delete','node-acceptance-uplink'],capture_output=True)
    subprocess.run(['ip','link','delete','node-uplink'],capture_output=True)
    subprocess.run(['ip','netns','delete',peer_name],capture_output=True)
    (args.media/'installed-network-result.json').write_text(json.dumps(report,indent=2)+'\n')
    os.sync()
