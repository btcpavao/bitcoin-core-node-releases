"""Portable JSON or authenticated GPG; atomic publication and bounded imports.

An unencrypted checksum detects damage, not an attacker. Its sensitive contents
are intentionally readable, as stated before export. No automatic downgrade.
Exports finish after writing and flushing; imports still authenticate/check data.
"""
import hashlib,json,os,time,uuid
from pathlib import Path
import settings_snapshot as ss
from gpg_backend import encrypt_file,decrypt_file
from chain_backup import external,identity,regular_at

ENVELOPE='bitcoin-core-node-portable-file'

def pack_plain(raw):
    payload=json.loads(raw)
    normalized=ss.canonical(payload)
    return ss.canonical(dict(format=ENVELOPE,version=1,sha256=hashlib.sha256(normalized).hexdigest(),payload=payload))

def unpack_plain(blob,limit):
    def unique(pairs):
        out={}
        for k,v in pairs:ss.require(k not in out,'Duplicate backup field.');out[k]=v
        return out
    try:data=json.loads(blob,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
    except (ValueError,UnicodeError,RecursionError):raise ss.SettingsError('Invalid unencrypted backup document.') from None
    ss.object_fields(data,('format','version','sha256','payload'))
    ss.require(data['format']==ENVELOPE and type(data['version']) is int and data['version']==1,'Unsupported backup format.')
    raw=ss.canonical(data['payload'])
    ss.require(len(raw)<=limit,'Backup exceeds the supported size limit.')
    ss.require(isinstance(data['sha256'],str) and hashlib.sha256(raw).hexdigest()==data['sha256'],'Backup checksum mismatch. No data was imported.')
    return raw

def publish(raw,directory,secret,caller,events,*,prefix,limit):
    ss.require(isinstance(secret,str),'Invalid backup passphrase.')
    ss.require(isinstance(raw,bytes) and len(raw)<=limit,'This backup exceeds the supported size limit.')
    ss.require(prefix in ('watch-only-wallets','bitcoin-core-config','bitcoin-node-settings'))
    encrypted=bool(secret)
    fd,resolved,_=external(directory,caller,writing=True)
    temp='.portable-partial-'+uuid.uuid4().hex
    name=prefix+'-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:10]+('.gpg' if encrypted else '.json')
    try:
        with ss.ram_work() as work:
            ss.require(os.statvfs(work).f_bavail*os.statvfs(work).f_frsize>len(raw)*4+16*1024**2,'Not enough private RAM to prepare this backup.')
            if encrypted:
                source=work/'payload';source.write_bytes(raw);source.chmod(0o600)
                out=work/'encrypted.gpg';events.update('Encrypting the backup',force=True)
                encrypt_file(source,out,secret,ram_root=work,progress=events,max_output_bytes=limit+1024*1024,verify_roundtrip=False)
                data=out.read_bytes()
            else:
                events.update('Preparing unencrypted backup',force=True)
                data=pack_plain(raw)
            events.check();events.update('Writing backup',force=True)
            with identity(caller):
                dest=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
                with os.fdopen(dest,'wb') as f:
                    ss.require(f.write(data)==len(data),'The destination did not accept the complete backup write.')
                    f.flush();os.fsync(f.fileno())
                # No destination re-read. Checksums/authentication remain in the
                # file format so restore can detect corruption before applying it.
                events.check();events.cancel_allowed=False
                reserve=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd);os.close(reserve)
                try:os.replace(temp,name,src_dir_fd=fd,dst_dir_fd=fd);os.fsync(fd)
                except BaseException:os.unlink(name,dir_fd=fd);raise
        return str(resolved/name)
    finally:
        with identity(caller):
            try:os.unlink(temp,dir_fd=fd)
            except FileNotFoundError:pass
        os.close(fd)

def read(filename,secret,caller,events,*,limit):
    ss.require(isinstance(filename,str) and len(filename)<=4096)
    path=Path(filename);ss.require(path.is_absolute() and path.suffix.lower() in ('.gpg','.json'),'Choose a .gpg or .json Node backup.')
    encrypted=path.suffix.lower()=='.gpg'
    ss.require(isinstance(secret,str) and (not encrypted or bool(secret)),'Enter the passphrase for this encrypted backup.')
    fd,_,_=external(str(path.parent),caller)
    try:
        f=regular_at(fd,path.name,caller)
        with os.fdopen(f,'rb') as stream:
            ss.require(os.fstat(stream.fileno()).st_size<=limit+1024*1024,'Backup exceeds the size limit.')
            blob=stream.read(limit+1024*1024+1)
    finally:os.close(fd)
    fingerprint=hashlib.sha256(blob).hexdigest()
    if not encrypted:
        events.update('Checking unencrypted backup integrity',force=True)
        return unpack_plain(blob,limit),fingerprint
    with ss.ram_work() as work:
        available=os.statvfs(work).f_bavail*os.statvfs(work).f_frsize
        output_limit=min(limit,max(0,(available-len(blob)-16*1024**2)//2))
        ss.require(output_limit>=1024**2,'Not enough private RAM to open this backup. Please close other applications and retry.')
        source=work/'input.gpg';source.write_bytes(blob);source.chmod(0o600)
        out=work/'payload';events.update('Decrypting and checking the backup',force=True)
        decrypt_file(source,out,secret,ram_root=work,progress=events,max_output_bytes=output_limit)
        return out.read_bytes(),fingerprint
