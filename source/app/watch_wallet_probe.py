"""Verify copied watch-only databases with pinned Core in an isolated namespace.

Only accepts generated private RAM paths. Never opens the installed wallets.
"""
import ctypes,hashlib,json,os,pwd,re,signal,subprocess,sys,time
from pathlib import Path
from chain_probe import verify_private_network
from upgrades import active_release
from rpc import CoreRPC,CoreError

def main():
    if os.geteuid()!=0 or len(sys.argv)!=4:raise RuntimeError()
    root=Path(sys.argv[1]);network=sys.argv[2];count=int(sys.argv[3])
    if (root.resolve()!=root or root.name!='probe' or root.parent.parent!=Path('/run')
            or not root.parent.name.startswith('core-node-settings-') or network not in ('main','regtest','signet')
            or not 1<=count<=32):raise RuntimeError()
    verify_private_network()
    subprocess.run(['/usr/sbin/ip','link','set','lo','up'],check=True,capture_output=True)
    release=active_release();binary=Path(release['path'])/'bin/bitcoind';info=binary.stat()
    with binary.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    if info.st_uid!=0 or info.st_mode&0o022 or digest!=release['binary_sha256']:raise RuntimeError()
    user=pwd.getpwnam('bitcoinnode');os.setgroups([]);os.setgid(user.pw_gid);os.setuid(user.pw_uid);os.umask(0o077)
    parent=os.getppid()
    if ctypes.CDLL(None).prctl(1,signal.SIGTERM,0,0,0)!=0 or os.getppid()!=parent:raise RuntimeError()
    args=[str(binary),'-datadir='+str(root),'-walletdir='+str(root/'wallets'),'-chain='+network,
          '-conf=/dev/null','-nosettings','-server=1','-daemon=0','-prune=550',
          '-networkactive=0','-listen=0','-dnsseed=0','-fixedseeds=0','-discover=0','-natpmp=0',
          '-listenonion=0','-connect=0','-walletbroadcast=0','-persistmempool=0','-dbcache=32','-par=1',
          '-rpcbind=127.0.0.1','-rpcallowip=127.0.0.1','-rpcport=19588','-debuglogfile=/dev/null','-printtoconsole=0']
    def interrupted(*_):raise InterruptedError()
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    pid=os.getpid()
    def guard():
        if ctypes.CDLL(None).prctl(1,signal.SIGTERM,0,0,0)!=0 or os.getppid()!=pid:os._exit(1)
    process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                             env=dict(PATH='/usr/bin:/bin',LANG='C.UTF-8',HOME=str(root)),preexec_fn=guard)
    rpc=CoreRPC(cookie=root/('' if network=='main' else network)/'.cookie',port=19588,timeout=30)
    try:
        end=time.monotonic()+90
        while True:
            if process.poll() is not None or time.monotonic()>end:raise RuntimeError('Isolated Core startup failed.')
            try:rpc('getblockchaininfo');break
            except CoreError:time.sleep(.1)
        for i in range(count):
            name=f'w{i:04d}';rpc('loadwallet',name,False)
            info=rpc('getwalletinfo',wallet=name)
            if info.get('private_keys_enabled') is not False or info.get('descriptors') is not True or info.get('external_signer') is True:
                raise RuntimeError('Only private-key-disabled descriptor wallets are accepted.')
            rpc('unloadwallet',name,False)
        rpc('stop');process.wait(timeout=90)
        if process.returncode:raise RuntimeError('Isolated Core shutdown failed.')
        print(json.dumps(dict(ok=True,count=count)),flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=90)
            except subprocess.TimeoutExpired:process.kill();process.wait()

if __name__=='__main__':
    try:main()
    except Exception:
        print('The copied database was not accepted as a supported watch-only wallet.',file=sys.stderr)
        sys.exit(1)
