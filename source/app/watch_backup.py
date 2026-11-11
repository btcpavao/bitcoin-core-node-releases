"""Native Core watch-only export/restore, encrypted as a portable collection.

Only Core's public-only export API is used. No source wallet files or private
keys are read. Restore is delegated to Core and never replaces an existing name.
"""
import base64,hashlib,json,os,pwd,re,shutil,stat,subprocess,tempfile,time,uuid
from pathlib import Path
from contextlib import contextmanager
import settings_snapshot as ss
import encrypted_transfer as crypt
from chain_backup import Events,ENV
from state import CONFIG,load_setup
from upgrades import active_release
from rpc import CoreRPC,CoreError

FORMAT='bitcoin-core-node-watch-wallets'
MAX_WALLET=32*1024**2
MAX_TOTAL=64*1024**2
MAX_PLAIN=96*1024**2
STATE=Path('/var/lib/core-node-watch-transfers')

def wallet_name(value):
    return (isinstance(value,str) and 0<len(value.encode())<=120 and not value.startswith('.')
            and not any(c in value for c in ('/','\\')) and not any(ord(c)<32 or ord(c)==127 for c in value))

def validate(data):
    ss.object_fields(data,('format','version','network','core_version','created_utc','wallets','skipped'))
    ss.require(data['format']==FORMAT and type(data['version']) is int and data['version']==1)
    ss.require(data['network'] in ('main','signet','regtest'))
    ss.require(isinstance(data['core_version'],str) and re.fullmatch(r'32\.\d{1,3}(?:\.\d{1,3})?',data['core_version']))
    ss.require(isinstance(data['created_utc'],str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',data['created_utc']))
    ss.require(type(data['skipped']) is int and 0<=data['skipped']<=1000)
    ss.require(isinstance(data['wallets'],list) and 1<=len(data['wallets'])<=32)
    names=set();total=0
    for row in data['wallets']:
        ss.object_fields(row,('name','sha256','public_export'))
        ss.require(wallet_name(row['name']) and row['name'] not in names,'Invalid or duplicate wallet name.')
        ss.require(isinstance(row['public_export'],str) and len(row['public_export'])<=4*((MAX_WALLET+2)//3))
        try:raw=base64.b64decode(row['public_export'],validate=True)
        except ValueError:raise ss.SettingsError('Invalid watch-only export.') from None
        ss.require(0<len(raw)<=MAX_WALLET and raw.startswith(b'SQLite format 3\0'),'Unsupported or oversized Core watch-only export.')
        ss.require(isinstance(row['sha256'],str) and hashlib.sha256(raw).hexdigest()==row['sha256'],'Watch-only export checksum mismatch.')
        total+=len(raw);names.add(row['name'])
    ss.require(total<=MAX_TOTAL,'Watch-only collection exceeds the 64 MiB transfer limit.')
    return data

def parse(raw):
    ss.require(len(raw)<=MAX_PLAIN)
    def unique(pairs):
        out={}
        for k,v in pairs:ss.require(k not in out);out[k]=v
        return out
    try:return validate(json.loads(raw,object_pairs_hook=unique))
    except (ValueError,TypeError,RecursionError):raise ss.SettingsError('Invalid watch-only backup document.') from None

def summary(data):
    return dict(scope='watch',created_utc=data['created_utc'],network=data['network'],
                wallets=[w['name'] for w in data['wallets']],skipped=data['skipped'])

def is_watch(info):
    return (info.get('private_keys_enabled') is False and info.get('descriptors') is True
            and info.get('external_signer') is not True)

@contextmanager
def core_ram():
    # The managed Core sandbox already permits this RAM-only workspace. The
    # generated subdirectory is private to its fixed unprivileged account.
    from gpg_backend import _tmpfs
    root=Path('/run/core-node-private/workspace')
    ss.require(root.is_dir() and not root.is_symlink(),'Private Workspace is unavailable.')
    fd=os.open(root,ss.DIR_FLAGS)
    try:_tmpfs(fd)
    finally:os.close(fd)
    ss.require(len(Path('/proc/swaps').read_text().splitlines())<=1,'Disable swap before secret configuration transfers.')
    core=pwd.getpwnam('bitcoinnode')
    with tempfile.TemporaryDirectory(prefix='.node-watch-transfer-',dir=root) as temp:
        path=Path(temp);path.chmod(0o700);os.chown(path,core.pw_uid,core.pw_gid)
        yield path

def check_copies(data,events):
    # Independent wallet-free source handling: only public exports are opened
    # in a separate upstream Core with no network adapters and no target data.
    core=pwd.getpwnam('bitcoinnode')
    with ss.ram_work() as work:
        work.chmod(0o711);probe=work/'probe';probe.mkdir(mode=0o700);os.chown(probe,core.pw_uid,core.pw_gid)
        wallets=probe/'wallets';wallets.mkdir(mode=0o700);os.chown(wallets,core.pw_uid,core.pw_gid)
        for i,row in enumerate(data['wallets']):
            folder=wallets/f'w{i:04d}';folder.mkdir(mode=0o700);os.chown(folder,core.pw_uid,core.pw_gid)
            p=folder/'wallet.dat';p.write_bytes(base64.b64decode(row['public_export']));p.chmod(0o600);os.chown(p,core.pw_uid,core.pw_gid)
        events.update('Verifying public-only exports with isolated Bitcoin Core',force=True)
        process=subprocess.Popen(['/usr/bin/unshare','--net','--','/usr/bin/python3',
                '/usr/lib/bitcoin-core-node/watch_wallet_probe.py',str(probe),data['network'],str(len(data['wallets']))],
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=ENV)
        try:
            deadline=time.monotonic()+300
            while process.poll() is None:
                events.check();ss.require(time.monotonic()<deadline,'Watch-only verification timed out. No existing wallet was changed.');time.sleep(.1)
            result=process.stdout.read(4097)
            ss.require(process.returncode==0 and len(result)<=4096,'Bitcoin Core rejected a public-only wallet export. No existing wallet was changed.')
            ss.require(json.loads(result)==dict(ok=True,count=len(data['wallets'])))
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=100)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            process.stdout.close()

def collect(rpc,events):
    chain=rpc('getblockchaininfo');loaded=set(rpc('listwallets'))
    names=[r['name'] for r in rpc('listwalletdir')['wallets']]
    ss.require(len(names)<=128,'Too many wallets to collect in one operation.')
    result=[];skipped=0;total=0
    with core_ram() as work:
        for name in names:
            events.check()
            if not wallet_name(name):skipped+=1;continue
            temporary=False
            try:
                if name not in loaded:
                    events.cancel_allowed=False;events.update('Opening a local wallet for type verification',force=True)
                    rpc('loadwallet',name);temporary=True
                info=rpc('getwalletinfo',wallet=name)
                if not is_watch(info):skipped+=1;continue
                events.cancel_allowed=False;events.update('Creating a native watch-only export',force=True)
                path=work/f'public-{len(result):04d}.dat'
                rpc('exportwatchonlywallet',str(path),wallet=name)
                # Upstream's public-only export can intentionally be group-writable.
                # Restrict only this generated RAM export, never the source wallet.
                fd=os.open(path,ss.FILE_FLAGS)
                try:
                    st=os.fstat(fd)
                    ss.require(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==pwd.getpwnam('bitcoinnode').pw_uid and st.st_size<=MAX_WALLET,'Unsafe native public-only export.')
                    os.fchmod(fd,0o600)
                finally:os.close(fd)
                raw=ss.safe_read(path,MAX_WALLET,owner=pwd.getpwnam('bitcoinnode').pw_uid)
                total+=len(raw);ss.require(total<=MAX_TOTAL and len(result)<32,'Watch-only exports exceed the supported size/count. No partial collection was published.')
                result.append(dict(name=name,sha256=hashlib.sha256(raw).hexdigest(),public_export=base64.b64encode(raw).decode()))
            finally:
                if temporary:rpc('unloadwallet',name)
                events.cancel_allowed=True
    ss.require(result,'No supported watch-only wallets were found. Signing wallets are never exported by this workflow.')
    return validate(dict(format=FORMAT,version=1,network=chain['chain'],core_version=active_release()['version'],
                created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),wallets=result,skipped=skipped))

def import_wallets(data,fingerprint,rpc,events):
    ss.require(not STATE.is_symlink());STATE.mkdir(mode=0o700,exist_ok=True)
    ss.require(STATE.stat().st_uid==0 and STATE.stat().st_mode&0o777==0o700)
    receipt=STATE/(fingerprint+'.json')
    old=ss.safe_read(receipt,16384,owner=0,optional=True)
    done=ss.json_load(old) if old else {};ss.require(isinstance(done,dict))
    existing={r['name'] for r in rpc('listwalletdir')['wallets']};renamed=0
    with core_ram() as work:
        for index,row in enumerate(data['wallets']):
            events.check()
            if row['name'] in done and done[row['name']] in existing:continue
            target=row['name']
            if target in existing:target='Restored '+str(index+1)+' '+uuid.uuid4().hex[:10];renamed+=1
            ss.require(wallet_name(target) and target not in existing)
            path=work/f'public-{index:04d}.dat';path.write_bytes(base64.b64decode(row['public_export']));path.chmod(0o600)
            core=pwd.getpwnam('bitcoinnode');os.chown(path,core.pw_uid,core.pw_gid)
            events.cancel_allowed=False;events.update('Restoring verified watch-only wallet with Bitcoin Core',force=True)
            try:
                rpc('restorewallet',target,str(path),True)
                ss.require(is_watch(rpc('getwalletinfo',wallet=target)),'Restored wallet did not pass its watch-only check.')
                done[row['name']]=target;existing.add(target);ss.atomic_private(receipt,done)
            except Exception:
                raise ss.SettingsError('Core could not finish this wallet restore. Existing wallets were not replaced. Completed wallets are kept; retry the same backup to resume, or inspect Bitcoin Core.') from None
            finally:events.cancel_allowed=True
    return dict(names=list(done.values()),renamed=renamed)

def _perform(action,request,caller,events):
    ss.require(os.geteuid()==0 and caller==pwd.getpwnam('node').pw_uid and (CONFIG/'installed').is_file())
    ss.require(action in ('watch-backup','watch-preview','watch-import'))
    ss.object_fields(request,{'path','passphrase'}|({'confirmed','fingerprint'} if action=='watch-import' else set()))
    ss.require(isinstance(request['path'],str) and isinstance(request['passphrase'],str) and len(request['passphrase'])<=512)
    rpc=CoreRPC(timeout=86400)
    try:chain=rpc('getblockchaininfo')
    except CoreError:raise ss.SettingsError('Please start Bitcoin Core before transferring watch-only wallets.') from None
    ss.require(chain['chain']==load_setup()['network'],'Running Core uses a different network.')
    if action=='watch-backup':
        fd,_,_=ss.external(request['path'],caller,writing=True);os.close(fd)
        data=collect(rpc,events);check_copies(data,events)
        filename=crypt.publish(ss.canonical(data),request['path'],request['passphrase'],caller,events,prefix='watch-only-wallets',limit=MAX_PLAIN)
        return dict(ok=True,file=filename,encrypted=bool(request['passphrase']),summary=summary(data))
    raw,fingerprint=crypt.read(request['path'],request['passphrase'],caller,events,limit=MAX_PLAIN)
    data=parse(raw)
    ss.require(data['network']==chain['chain'],'Watch-only backup is for a different Bitcoin network.')
    ss.require(data['core_version']==active_release()['version'],'Restore with the same Core version used to create the backup.')
    check_copies(data,events)
    if action=='watch-preview':return dict(ok=True,summary=summary(data),fingerprint=fingerprint)
    ss.require(request['confirmed'] is True and request['fingerprint']==fingerprint,'Backup changed after review. Please review again.')
    return dict(ok=True,summary=summary(data),**import_wallets(data,fingerprint,rpc,events))


def perform(action,request,caller,events):
    # Native Core calls may need a rescan; protect their lifetime without a
    # background task or an unbounded shell. All mutation is still user-confirmed.
    inhibitor=subprocess.Popen(['/usr/bin/systemd-inhibit','--what=shutdown:sleep','--mode=block',
            '--who=Bitcoin Core Node','--why=Watch-only wallet transfer','/usr/bin/cat'],
            stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=ENV)
    try:
        time.sleep(.15);ss.require(inhibitor.poll() is None,'The wallet transfer could not be protected from shutdown.')
        return _perform(action,request,caller,events)
    finally:
        inhibitor.stdin.close()
        try:inhibitor.wait(timeout=5)
        except subprocess.TimeoutExpired:inhibitor.terminate();inhibitor.wait(timeout=5)
