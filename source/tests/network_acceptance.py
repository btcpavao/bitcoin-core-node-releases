#!/usr/bin/python3
"""Exercise production nft policy and a real WireGuard tunnel in disposable namespaces.

Run only on an owned CI runner: unshare --mount --net --propagation private --
python3 tests/network_acceptance.py. Never touches the runner's network namespace.
Tor loopback is a transport fixture, not a Tor anonymity or bootstrap test.
"""
import ipaddress
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from network import firewall

if os.geteuid()!=0 or os.environ.get('NODE_DISPOSABLE_NETWORK_TEST')!='1':
    sys.exit('This test requires an explicitly selected disposable privileged CI environment.')
if Path('/proc/self/ns/net').stat().st_ino==Path('/proc/1/ns/net').stat().st_ino:
    sys.exit('Refusing to modify the host network namespace.')
IP=shutil.which('ip');NFT=shutil.which('nft');WG=shutil.which('wg')
PEER='node-fixture-'+str(os.getpid())
UID=62000

def run(args,**kwargs):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=20,**kwargs)
def peer(*args,**kwargs):return run([IP,'netns','exec',PEER,*args],**kwargs)
def apply(mode,exists=True):
    rules=firewall(mode,UID,ipaddress.ip_address('192.0.2.2'),51820,replace=exists)
    run([NFT,'--check','--file','-'],input=rules)
    run([NFT,'--file','-'],input=rules)

SERVER='''import socket,select
sockets=[]
for af,host,port in [(socket.AF_INET,'0.0.0.0',19444),(socket.AF_INET,'0.0.0.0',53),(socket.AF_INET6,'::',19444)]:
 s=socket.socket(af,socket.SOCK_DGRAM)
 if af==socket.AF_INET6:s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
 s.bind((host,port));sockets.append(s)
print('READY',flush=True)
while True:
 for s in select.select(sockets,[],[])[0]:
  data,address=s.recvfrom(1024);s.sendto(data,address)
'''
SEND='''import socket,sys,os
os.setgid(62000);os.setuid(62000)
s=socket.socket(socket.AF_INET6 if ':' in sys.argv[1] else socket.AF_INET,socket.SOCK_DGRAM)
s.settimeout(1)
try:
 s.sendto(b'node-disposable-test',(sys.argv[1],int(sys.argv[2])))
 print(s.recvfrom(128)[0]==b'node-disposable-test')
except OSError:print(False)
'''
def reaches(address,port=19444):
    return run([sys.executable,'-c',SEND,address,str(port)]).stdout.strip()=='True'

server=None
try:
    run([IP,'link','set','lo','up'])
    run([IP,'netns','add',PEER])
    run([IP,'link','add','outside','type','veth','peer','name','provider'])
    run([IP,'link','set','provider','netns',PEER])
    run([IP,'addr','add','192.0.2.1/24','dev','outside'])
    run([IP,'-6','addr','add','2001:db8:42::1/64','dev','outside','nodad'])
    run([IP,'link','set','outside','up'])
    peer(IP,'addr','add','192.0.2.2/24','dev','provider')
    peer(IP,'-6','addr','add','2001:db8:42::2/64','dev','provider','nodad')
    peer(IP,'link','set','provider','up');peer(IP,'link','set','lo','up')
    run([IP,'route','add','default','via','192.0.2.2','metric','1000'])
    server=subprocess.Popen([IP,'netns','exec',PEER,sys.executable,'-u','-c',SERVER],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if not select.select([server.stdout],[],[],10)[0] or server.stdout.readline().strip()!='READY':
        raise RuntimeError('Disposable echo fixture did not start.')
    apply('clearnet',exists=False)
    assert reaches('192.0.2.2') and reaches('2001:db8:42::2')
    print('PASS real clearnet IPv4/IPv6 packets')
    apply('unconfirmed')
    assert not reaches('192.0.2.2') and not reaches('2001:db8:42::2')
    print('PASS preconfirmation daemon egress block')
    apply('tor')
    assert not reaches('192.0.2.2') and not reaches('192.0.2.2',53) and not reaches('2001:db8:42::2')
    local=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);local.bind(('127.0.0.1',19445));local.settimeout(2)
    child=subprocess.Popen([sys.executable,'-c',SEND,'127.0.0.1','19445'],stdout=subprocess.PIPE,text=True)
    message,address=local.recvfrom(128);local.sendto(message,address)
    assert child.communicate(timeout=5)[0].strip()=='True';local.close()
    assert not reaches('127.0.0.1',19445) and not reaches('192.0.2.2')
    print('PASS Tor-scope direct/DNS/IPv6 block, loopback proxy access, proxy-failure no direct fallback')
    with tempfile.TemporaryDirectory(prefix='node-wg-',dir='/dev/shm') as temp:
        root=Path(temp)
        client_private=run([WG,'genkey']).stdout.strip();server_private=run([WG,'genkey']).stdout.strip()
        client_public=run([WG,'pubkey'],input=client_private+'\n').stdout.strip()
        server_public=run([WG,'pubkey'],input=server_private+'\n').stdout.strip()
        client_key=root/'client';provider_key=root/'provider'
        for path,value in [(client_key,client_private),(provider_key,server_private)]:
            path.write_text(value+'\n');path.chmod(0o600)
        run([IP,'link','add','core-node','type','wireguard'])
        peer(IP,'link','add','provider-wg','type','wireguard')
        run([WG,'set','core-node','private-key',str(client_key),'peer',server_public,'allowed-ips','0.0.0.0/0','endpoint','192.0.2.2:51820'])
        peer(WG,'set','provider-wg','private-key',str(provider_key),'listen-port','51820','peer',client_public,'allowed-ips','172.31.0.1/32')
        run([IP,'addr','add','172.31.0.1/30','dev','core-node'])
        peer(IP,'addr','add','172.31.0.2/30','dev','provider-wg')
        run([IP,'link','set','core-node','up']);peer(IP,'link','set','provider-wg','up')
        run([IP,'route','add','default','dev','core-node','metric','100'])
        apply('wireguard')
        assert reaches('172.31.0.2') and reaches('172.31.0.2',53)
        assert not reaches('192.0.2.2') and not reaches('192.0.2.2',53) and not reaches('2001:db8:42::2')
        print('PASS real WireGuard handshake, tunnel data/DNS and blocked external IPv4/DNS/IPv6')
        run([IP,'link','delete','core-node'])
        assert not reaches('192.0.2.2') and not reaches('192.0.2.2',53) and not reaches('2001:db8:42::2')
        print('PASS tunnel removal kill switch with live clearnet route still present')
    apply('clearnet')
    assert reaches('192.0.2.2')
    apply('tor')
    assert not reaches('192.0.2.2')
    print('PASS explicit profile switching')
    print('Not established: actual Tor bootstrap, installed boot ordering, NetworkManager DNS configuration or private-broadcast delivery.')
finally:
    if server is not None:
        server.terminate();server.wait(timeout=10)
    subprocess.run([IP,'netns','delete',PEER],capture_output=True)
