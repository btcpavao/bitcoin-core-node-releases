"""Private-network, wallet-free database validation for the root chain broker."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import subprocess
import sys
import time
import tempfile
import ctypes
from state import DATA
from upgrades import active_release
from rpc import CoreRPC, CoreError


def verify_private_network():
    # sysfs belongs to the namespace in which it was mounted. After unshare
    # --net, /sys/class/net can still show the desktop's physical interfaces.
    # Check the actual current namespace and query its interface list instead.
    current=os.stat('/proc/self/ns/net')
    parent=os.stat('/proc/'+str(os.getppid())+'/ns/net')
    if (current.st_dev,current.st_ino)==(parent.st_dev,parent.st_ino):
        raise RuntimeError('Network isolation was not established.')
    if sorted(name for _,name in socket.if_nameindex())!=['lo']:
        raise RuntimeError('Validation namespace contains a network interface.')


def main():
    if os.geteuid() != 0 or len(sys.argv) != 3:
        raise RuntimeError('Invalid validation context.')
    root = Path(sys.argv[1]); network = sys.argv[2]
    if (root.resolve() != root or network not in ('main', 'regtest', 'signet') or
            not (root == DATA or (root.name == 'candidate' and root.parent.parent == DATA
                                 and root.parent.name.startswith('.core-node-chain-')))):
        raise RuntimeError('Invalid validation directory.')
    # unshare must have provided an isolated namespace, never just a flag
    # promising not to connect. There can be no physical or virtual NIC.
    verify_private_network()
    subprocess.run(['/usr/sbin/ip', 'link', 'set', 'lo', 'up'], check=True, capture_output=True)
    release = active_release(); binary = Path(release['path']) / 'bin/bitcoind'
    info = binary.stat()
    with binary.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if info.st_uid != 0 or info.st_mode & 0o022 or digest != release['binary_sha256']:
        raise RuntimeError('Unverified Core executable.')
    account = pwd.getpwnam('bitcoinnode')
    os.setgroups([]); os.setgid(account.pw_gid); os.setuid(account.pw_uid); os.umask(0o077)
    # A vanished broker must not leave a validation daemon holding the chain
    # directory. Credential changes clear this setting, so set it afterwards.
    if ctypes.CDLL(None).prctl(1,signal.SIGTERM,0,0,0)!=0:raise RuntimeError('Parent lifetime guard failed.')
    env = {'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8', 'HOME':'/var/lib/bitcoin-core-node/gui'}
    args = [str(binary), '-conf=/dev/null', '-nosettings', '-datadir='+str(root), '-chain='+network,
            '-disablewallet=1', '-server=1', '-daemon=0', '-prune=1', '-networkactive=0', '-listen=0',
            '-dnsseed=0', '-fixedseeds=0', '-discover=0', '-natpmp=0', '-listenonion=0', '-connect=0',
            '-rpcbind=127.0.0.1', '-rpcallowip=127.0.0.1', '-rpcport=18487', '-debuglogfile=/dev/null',
            '-printtoconsole=0', '-persistmempool=0', '-dbcache=64', '-par=1']
    def interrupted(*_): raise InterruptedError()
    signal.signal(signal.SIGTERM, interrupted); signal.signal(signal.SIGINT, interrupted)
    parent_pid=os.getpid()
    def child_guard():
        if ctypes.CDLL(None).prctl(1,signal.SIGTERM,0,0,0)!=0 or os.getppid()!=parent_pid:os._exit(1)
    diagnostic = tempfile.TemporaryFile()
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=diagnostic, env=env,preexec_fn=child_guard)
    cookie = root / ('' if network == 'main' else network) / '.cookie'
    rpc = CoreRPC(cookie=cookie, port=18487, timeout=2)
    try:
        end = time.monotonic() + 780
        while True:
            if process.poll() is not None:
                diagnostic.seek(0, os.SEEK_END)
                diagnostic.seek(max(0, diagnostic.tell() - 1800))
                reason = ' '.join(diagnostic.read(1800).decode('utf-8', 'replace').split())
                raise RuntimeError('Core refused the copied databases.' + (' ' + reason if reason else ' Exit code: ' + str(process.returncode)))
            try:
                details = rpc('getblockchaininfo'); break
            except CoreError:
                if time.monotonic() > end: raise RuntimeError('Validation timed out.')
                time.sleep(.2)
        rpc('stop')
        if process.wait(timeout=120) != 0: raise RuntimeError('Validation did not stop cleanly.')
        print(json.dumps(details), flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
        diagnostic.close()


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        # Wallets are disabled and RPC credentials are never logged.
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        sys.exit(1)
