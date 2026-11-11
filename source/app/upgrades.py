"""Explicit, signed upstream maintenance within the supported Core major version."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.request

from state import CONFIG, DATA, CORE_SHA256, CORE_GUI_SHA256
from wallets import WalletError, read_file

BASELINE={'version':'32.1','binary_sha256':CORE_SHA256,'gui_sha256':CORE_GUI_SHA256,'path':'/opt/bitcoin-core/32.1'}
MAX_ARCHIVE=160*1024*1024
KEY_HASH='da74e119bc949131f24ec08c406729e343b40bc44cd89be51cffcce1d28feec7'
KEYS=Path('/usr/share/bitcoin-core-node/release-keys.asc')
if not KEYS.exists():KEYS=Path(__file__).resolve().parents[1]/'runtime/usr/share/bitcoin-core-node/release-keys.asc'

def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{0,2}\.[0-9]{1,3}(?:\.[0-9]{1,3})?',value):
        raise WalletError('Please choose an official stable Core version.')
    numbers=tuple(map(int,value.split('.')))
    return numbers+(0,)*(3-len(numbers))

def active_release():
    path=CONFIG/'core-release.json'
    if not path.exists():return dict(BASELINE)
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_size>4096:
        raise WalletError('The active Core provenance record is unsafe.')
    try:record=json.loads(path.read_bytes())
    except ValueError:raise WalletError('The active Core provenance record is invalid.') from None
    if (version(record.get('version'))[0]!=32 or not re.fullmatch('[0-9a-f]{64}',record.get('binary_sha256',''))
            or not re.fullmatch('[0-9a-f]{64}',record.get('gui_sha256',''))
            or not re.fullmatch('[0-9a-f]{64}',record.get('archive_sha256',''))
            or record.get('path')!='/opt/bitcoin-core/versions/'+record['version']+'-'+record['archive_sha256']):
        raise WalletError('The active Core provenance record does not match its version.')
    return record

def latest_release():
    request=urllib.request.Request('https://api.github.com/repos/bitcoin/bitcoin/releases/latest',headers={'User-Agent':'Bitcoin-Core-Node','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request,timeout=30) as response:data=response.read(512*1024+1)
    if len(data)>512*1024:raise WalletError('The upstream version response is too large.')
    record=json.loads(data);tag=record.get('tag_name','')
    if record.get('prerelease') or record.get('draft') or not tag.startswith('v'):
        raise WalletError('Upstream did not report a stable Core release.')
    candidate=tag[1:];version(candidate)
    return {'version':candidate,'supported':version(candidate)[0]==32,'current':active_release()['version']}

def download_release(number,directory):
    if version(number)[0]!=32:raise WalletError('A new major Core version requires a reviewed Node system update.')
    directory=Path(directory)
    for name,limit in [('SHA256SUMS',256*1024),('SHA256SUMS.asc',1024*1024),('bitcoin-'+number+'-x86_64-linux-gnu.tar.gz',MAX_ARCHIVE)]:
        url='https://bitcoincore.org/bin/bitcoin-core-'+number+'/'+name
        with urllib.request.urlopen(url,timeout=120) as response, (directory/name).open('xb') as target:
            total=0
            while block:=response.read(1024*1024):
                total+=len(block)
                if total>limit:raise WalletError('The upstream file exceeds its size limit.')
                target.write(block)
            target.flush();os.fsync(target.fileno())
    return inspect_bundle(directory,number)

def inspect_bundle(directory,number):
    if version(number)[0]!=32:raise WalletError('Only Core 32 maintenance releases are supported by this Node version.')
    directory=Path(directory)
    sums=read_file(directory/'SHA256SUMS',256*1024)
    signature=read_file(directory/'SHA256SUMS.asc',1024*1024)
    archive=read_file(directory/('bitcoin-'+number+'-x86_64-linux-gnu.tar.gz'),MAX_ARCHIVE)
    keys=read_file(KEYS,256*1024)
    if hashlib.sha256(keys).hexdigest()!=KEY_HASH:raise WalletError('The bundled release-signing keys do not match their provenance pin.')
    with tempfile.TemporaryDirectory(prefix='node-release-verify-') as folder:
        root=Path(folder);root.chmod(0o700)
        (root/'SHA256SUMS').write_bytes(sums);(root/'SHA256SUMS.asc').write_bytes(signature)
        result=subprocess.run(['/usr/bin/gpg','--no-options','--batch','--homedir',folder,'--dearmor'],input=keys,capture_output=True,timeout=30)
        if result.returncode:raise WalletError('Release key conversion failed.')
        (root/'keys.gpg').write_bytes(result.stdout)
        result=subprocess.run(['/usr/bin/gpgv','--homedir',folder,'--keyring',str(root/'keys.gpg'),'--status-fd','1',str(root/'SHA256SUMS.asc'),str(root/'SHA256SUMS')],capture_output=True,text=True,timeout=30)
        lines=result.stdout.splitlines()
        groups=[]
        for line in lines:
            if line.startswith('[GNUPG:] NEWSIG'):groups.append([])
            if groups:groups[-1].append(line)
        signers=sorted({line.split()[-1] for group in groups
            if any(row.startswith('[GNUPG:] GOODSIG ') for row in group)
            and not any(row.startswith('[GNUPG:] '+bad+' ') for row in group for bad in ['EXPSIG','EXPKEYSIG','REVKEYSIG'])
            for line in group if line.startswith('[GNUPG:] VALIDSIG ')})
        if len(signers)<2 or any(line.startswith('[GNUPG:] BADSIG ') for line in lines):
            raise WalletError('At least two valid, distinct bundled release signers are required. No Core files were changed.')
    expected=[];filename='bitcoin-'+number+'-x86_64-linux-gnu.tar.gz'
    for line in sums.decode('ascii').splitlines():
        parts=line.split()
        if len(parts)==2 and parts[1].lstrip('*')==filename:expected.append(parts[0])
    digest=hashlib.sha256(archive).hexdigest()
    if expected!=[digest]:raise WalletError('The Core archive does not match the signed checksums.')
    files={};total=0;prefix='bitcoin-'+number
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as bundle:
        for entry in bundle:
            path=PurePosixPath(entry.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!=prefix or entry.issym() or entry.islnk() or not (entry.isdir() or entry.isfile()):
                raise WalletError('The signed archive has an unsupported file layout.')
            if entry.isdir():continue
            total+=entry.size
            if total>600*1024*1024 or entry.size>160*1024*1024:raise WalletError('The expanded Core archive is too large.')
            relative=str(PurePosixPath(*path.parts[1:]))
            if relative in files:raise WalletError('Duplicate file in Core release.')
            stream=bundle.extractfile(entry)
            if stream is None:raise WalletError('Incomplete Core archive.')
            content=stream.read(entry.size+1)
            if len(content)!=entry.size:raise WalletError('Incomplete Core archive member.')
            files[relative]=(content,0o755 if entry.mode&0o111 else 0o644)
    if any(name not in files for name in ['bin/bitcoind','bin/bitcoin-qt','bin/bitcoin-cli','bin/bitcoin-wallet']):
        raise WalletError('Required upstream Core executables are missing.')
    daemon=files['bin/bitcoind'][0]
    if not daemon.startswith(b'\x7fELF'):raise WalletError('Unsupported Core executable format.')
    return {'version':number,'archive_sha256':digest,'binary_sha256':hashlib.sha256(daemon).hexdigest(),'gui_sha256':hashlib.sha256(files['bin/bitcoin-qt'][0]).hexdigest(),'signers':signers,'files':files}

def install_bundle(request,caller_uid):
    """Called only by the serialized authenticated root administrator helper."""
    if not isinstance(request,dict) or set(request)!={'directory','version','archive_sha256','current_sha256'}:
        raise WalletError('Invalid Core maintenance request.')
    directory=Path(request['directory'])
    if not directory.is_absolute() or directory.resolve()!=directory or directory.stat().st_uid!=caller_uid:
        raise WalletError('The downloaded release must belong to the authenticated local user.')
    for path in directory.iterdir():
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=caller_uid or info.st_nlink!=1:
            raise WalletError('The release directory contains an unsafe input file.')
    current=active_release()
    if current['binary_sha256']!=request['current_sha256'] or version(request['version'])<version(current['version']):
        raise WalletError('Core changed since review, or the request is a downgrade. Please review again.')
    verified=inspect_bundle(directory,request['version'])
    if verified['archive_sha256']!=request['archive_sha256']:
        raise WalletError('The downloaded archive changed after review.')
    wallet_bytes=sum(path.lstat().st_size for path in (DATA/'wallets').rglob('*') if path.is_file() and not path.is_symlink())
    install_bytes=sum(len(content) for content,mode in verified['files'].values())
    required=wallet_bytes+install_bytes+1024**3
    if min(shutil.disk_usage('/opt').free,shutil.disk_usage('/var/lib/bitcoin-core-node').free)<required:
        raise WalletError('Please free sufficient disk space for the release and a complete wallet snapshot before maintenance.')
    parent=Path('/opt/bitcoin-core/versions');parent.mkdir(mode=0o755,exist_ok=True);parent.chmod(0o755)
    target=parent/(verified['version']+'-'+verified['archive_sha256'])
    if target.exists():raise WalletError('These exact Core bytes are already staged. Please inspect local maintenance records.')
    staged=Path(tempfile.mkdtemp(prefix='.release-',dir=parent));service_stopped=False
    try:
        staged.chmod(0o755)
        for name,(content,mode) in verified.pop('files').items():
            destination=staged/name;destination.parent.mkdir(parents=True,exist_ok=True)
            with destination.open('xb') as stream:
                os.fchmod(stream.fileno(),mode);stream.write(content);stream.flush();os.fsync(stream.fileno())
        for path in staged.rglob('*'):
            if path.is_dir():path.chmod(0o755)
        output=subprocess.run([str(staged/'bin/bitcoind'),'--version'],capture_output=True,text=True,timeout=15,check=True).stdout
        if not re.search(r'\bv'+re.escape(verified['version'])+r'(?:\.0)?\b',output):
            raise WalletError('The signed executable reports a different Core version.')
        was_running = subprocess.run(['/usr/bin/systemctl','is-active','--quiet','bitcoin-core-node.service']).returncode == 0
        subprocess.run(['/usr/bin/systemctl','stop','bitcoin-core-node.service'],check=True,timeout=330)
        service_stopped=True
        if subprocess.run(['/usr/bin/systemctl','is-active','--quiet','bitcoin-core-node.service']).returncode==0:
            raise WalletError('Core did not stop cleanly; activation was refused.')
        stopped=subprocess.run(['/usr/bin/systemctl','show','--property=Result','--value','bitcoin-core-node.service'],capture_output=True,text=True,check=True,timeout=15).stdout.strip()
        if stopped!='success':raise WalletError('Core did not report a clean service shutdown. Upgrade activation was refused; please inspect the daemon before maintenance.')
        backup=Path('/var/lib/bitcoin-core-node/update-backups')/str(time.time_ns())
        backup.mkdir(parents=True,mode=0o700)
        shutil.copytree(DATA/'wallets',backup/'wallets',symlinks=True)
        if (DATA/'settings.json').exists():shutil.copy2(DATA/'settings.json',backup/'settings.json',follow_symlinks=False)
        (backup/'previous-core.json').write_text(json.dumps(current,indent=2)+'\n')
        os.sync()
        os.rename(staged,target)
        record={**verified,'path':str(target),'backup':str(backup)}
        fd,name=tempfile.mkstemp(prefix='.core-release-',dir=CONFIG)
        try:
            with os.fdopen(fd,'w') as stream:
                os.fchmod(stream.fileno(),0o644);json.dump(record,stream,sort_keys=True,indent=2);stream.flush();os.fsync(stream.fileno())
            os.replace(name,CONFIG/'core-release.json');os.sync()
        finally:
            if os.path.exists(name):os.unlink(name)
        if not was_running:
            service_stopped=False
            return {'ok':True,'version':verified['version'],'backup':str(backup),'signers':verified['signers'],'running':False}
        subprocess.run(['/usr/bin/systemctl','start','bitcoin-core-node.service'],check=True,timeout=120)
        from rpc import CoreRPC
        rpc=CoreRPC()
        for _ in range(300):
            try:
                if ('/'+ 'Satoshi:'+verified['version']) not in rpc('getnetworkinfo')['subversion']:
                    raise WalletError('The running Core version differs from the verified release.')
                service_stopped=False
                return {'ok':True,'version':verified['version'],'backup':str(backup),'signers':verified['signers']}
            except Exception:time.sleep(.1)
        subprocess.run(['/usr/bin/systemctl','stop','bitcoin-core-node.service'],timeout=330)
        raise WalletError('The verified upgrade did not become healthy. Core is stopped; the previous binaries and wallet snapshot are retained for deliberate recovery.')
    finally:
        if service_stopped:
            subprocess.run(['/usr/bin/systemctl','stop','bitcoin-core-node.service'],capture_output=True,timeout=330)
        if staged.exists():shutil.rmtree(staged)
