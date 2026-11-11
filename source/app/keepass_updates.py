"""Official KeePassXC AppImage releases, verified before extraction or activation."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request
import urllib.error
import urllib.parse
import socket
import ssl
import time
import http.client
import math
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

FINGERPRINT = 'BF5A669F2272CF4324C1FDA8CFB4C2166397D0D2'
KEY = Path('/usr/share/bitcoin-core-node/keepassxc-release-key.asc')
RELEASES = Path('/opt/keepassxc')
API = 'https://api.github.com/repos/keepassxreboot/keepassxc/releases/'
DOWNLOAD = 'https://github.com/keepassxreboot/keepassxc/releases/download/'


class UpdateError(Exception):
    pass


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]?\.[0-9]{1,3}\.[0-9]{1,3}', value):
        raise UpdateError('The official KeePassXC release record is invalid.')
    return tuple(map(int, value.split('.')))


DOWNLOAD_PAGE = 'https://keepassxc.org/download/'


class DownloadError(UpdateError):
    """Sanitized transport failure; metadata fallback never disables TLS."""
    def __init__(self, message, *, kind, status=None, retry_after=None):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after
        self.fallback_allowed = kind in ('dns', 'timeout', 'connection') or (
            kind == 'http' and (status in (403, 429) or 500 <= status <= 599))


def trusted_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.fragment
                or any(ord(c) < 32 for c in url)):
            return False
        if parsed.hostname == 'keepassxc.org':
            return parsed.path == '/download/' and not parsed.query
        if parsed.hostname == 'api.github.com':
            return parsed.path.startswith('/repos/keepassxreboot/keepassxc/releases/')
        if parsed.hostname == 'github.com':
            return parsed.path.startswith('/keepassxreboot/keepassxc/releases/download/')
        return parsed.hostname in ('release-assets.githubusercontent.com', 'objects.githubusercontent.com')
    except (ValueError, TypeError):
        return False


class _ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not trusted_url(newurl):
            raise UpdateError('A software redirect outside the approved HTTPS release hosts was refused.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(request):
    # The default HTTPS handler verifies certificates; never use an insecure context.
    return urllib.request.build_opener(_ReleaseRedirect()).open(request, timeout=20)


def _transport_error(exc, host):
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        retry = exc.headers.get('Retry-After') if exc.headers else None
        if retry is not None:
            try: retry = float(retry)
            except (ValueError, TypeError):
                try: retry = parsedate_to_datetime(retry).timestamp() - time.time()
                except (ValueError, TypeError, OverflowError): retry = None
            if retry is not None:
                retry = max(0.0, retry) if math.isfinite(retry) else None
        if code in (403, 429):
            message = f'{host} refused or rate-limited the update check (HTTP {code}). Please retry later.'
        elif 500 <= code <= 599:
            message = f'{host} is temporarily unavailable (HTTP {code}). This is a server or gateway response, not proof of a local clock problem.'
        else:
            message = f'{host} returned HTTP {code}. The release could not be downloaded; the installed version was kept.'
        return DownloadError(message, kind='http', status=code, retry_after=retry)
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError):
        return DownloadError(f'TLS certificate verification failed for {host}. Please check the actual date/time and certificate trust; the connection was not bypassed.', kind='tls')
    if isinstance(reason, ssl.SSLError):
        return DownloadError(f'The secure TLS connection to {host} failed. No unverified download was accepted.', kind='tls')
    if isinstance(reason, socket.gaierror):
        return DownloadError(f'DNS could not resolve {host}. Please check the system DNS or VPN connection.', kind='dns')
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return DownloadError(f'The connection to {host} timed out. Please retry or check the route to this server.', kind='timeout')
    return DownloadError(f'The connection to {host} failed. Other Internet services may still work; please retry this update source.', kind='connection')


def _fetch_once(url, destination, limit):
    if not trusted_url(url):
        raise UpdateError('An unofficial or insecure software URL was refused.')
    host = urllib.parse.urlsplit(url).hostname
    accept = ('application/vnd.github+json' if host == 'api.github.com' else
              'text/html' if host == 'keepassxc.org' else 'application/octet-stream')
    request = urllib.request.Request(url, headers={'User-Agent': 'Bitcoin-Core-Node/1.0',
        'Accept': accept, 'Cache-Control': 'no-cache'})
    output = None
    try:
        try:
            response = _open(request)
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise _transport_error(exc, host) from exc
        with response:
            if not trusted_url(response.url):
                raise UpdateError('A software response outside approved HTTPS release hosts was refused.')
            if destination is not None:
                try: output = destination.open('wb')
                except OSError as exc:
                    raise UpdateError('The software download could not be saved locally. Please check disk space and permissions.') from exc
            total = 0
            chunks = []
            while True:
                try: part = response.read(1024 * 1024)
                except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
                    raise _transport_error(exc, host) from exc
                if not part: break
                total += len(part)
                if total > limit:
                    raise UpdateError('The software download exceeds the allowed size.')
                if output is not None:
                    try: output.write(part)
                    except OSError as exc:
                        raise UpdateError('The software download could not be saved locally. Please check disk space and permissions.') from exc
                else: chunks.append(part)
            if output is not None:
                try: output.flush()
                except OSError as exc:
                    raise UpdateError('The software download could not be saved locally. Please check disk space and permissions.') from exc
            return b''.join(chunks) if destination is None else total
    finally:
        if output is not None: output.close()


def fetch(url, destination=None, limit=1024*1024):
    for attempt in range(2):
        try:
            return _fetch_once(url, destination, limit)
        except DownloadError as exc:
            # Do not hammer rate-limited endpoints. Longer Retry-After values
            # are respected by returning to the user instead of retrying early.
            transient = exc.kind in ('timeout', 'connection') or (
                exc.kind == 'http' and exc.status in (500, 502, 503, 504))
            if attempt or not transient or (exc.retry_after is not None and exc.retry_after > 2):
                raise
            time.sleep(max(1, exc.retry_after or 0))


class _DownloadLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = set()
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            link = dict(attrs).get('href')
            if isinstance(link, str): self.links.add(link)


def website_release(data, number=None):
    """Read only exact stable x86-64 links and their detached signatures."""
    try:
        parser = _DownloadLinks()
        parser.feed(data.decode('utf-8'))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise UpdateError('The official KeePassXC download page could not be read.') from exc
    matches = []
    for url in parser.links:
        match = re.fullmatch(re.escape(DOWNLOAD) + r'([1-9][0-9]?\.[0-9]{1,3}\.[0-9]{1,3})/(KeePassXC-\1(?:-([1-9][0-9]{0,2}))?-x86_64\.AppImage)', url)
        if match and url + '.sig' in parser.links:
            tag, name, revision = match.groups()
            version(tag)
            matches.append((tag, int(revision or 0), name, url))
    if len({row[0] for row in matches}) != 1:
        raise UpdateError('The official KeePassXC page did not identify one stable x86-64 release with its signature. No version was guessed.')
    tag, _, name, url = max(matches, key=lambda row: row[1])
    if number is not None and tag != number:
        raise UpdateError('The official download page does not list the requested KeePassXC version. No different release was substituted.')
    return dict(version=tag, name=name, url=url)


def release_record(record):
    if not isinstance(record, dict) or record.get('draft') is not False or record.get('prerelease') is not False:
        raise UpdateError('Only official stable KeePassXC releases are accepted.')
    number = record.get('tag_name')
    version(number)
    matches = []
    for asset in record.get('assets', []):
        name = asset.get('name', '')
        match = re.fullmatch(r'KeePassXC-' + re.escape(number) + r'(?:-([1-9][0-9]{0,2}))?-x86_64\.AppImage', name)
        if match:
            url = DOWNLOAD + number + '/' + name
            if asset.get('browser_download_url') != url:
                raise UpdateError('An unofficial KeePassXC download was refused.')
            matches.append((int(match[1] or 0), name, url))
    if not matches:
        raise UpdateError('The official release has no supported x86-64 AppImage.')
    _, name, url = max(matches)
    return dict(version=number, name=name, url=url)


def latest_release(number=None):
    if number is not None:
        version(number)
    try:
        data = fetch(API + ('latest' if number is None else 'tags/' + number))
    except DownloadError as primary:
        if not primary.fallback_allowed:
            raise
        try:
            candidate = website_release(fetch(DOWNLOAD_PAGE), number)
        except UpdateError as secondary:
            raise UpdateError('KeePassXC update check is incomplete. GitHub: ' + str(primary) +
                              ' Official download page: ' + str(secondary)) from secondary
        candidate.update(metadata_source=DOWNLOAD_PAGE,
                         metadata_note='GitHub release API unavailable; checked the official KeePassXC download page instead. ' + str(primary))
        return candidate
    try:
        candidate = release_record(json.loads(data))
    except (ValueError, TypeError, KeyError) as exc:
        raise UpdateError('The official KeePassXC release record could not be read.') from exc
    candidate['metadata_source'] = 'GitHub release API'
    return candidate


def current_release(root=RELEASES):
    try:
        path = root / 'current/node-release.json'
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
            raise ValueError()
        record = json.loads(resolved.read_bytes())
        version(record['version'])
        if record['primary_signer'] != FINGERPRINT or not re.fullmatch('[a-f0-9]{64}', record['sha256']):
            raise ValueError()
        return record
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise UpdateError('The installed KeePassXC release record is unavailable.') from exc


def verify_image(image, signature, key=KEY):
    with tempfile.TemporaryDirectory(prefix='node-keepass-signature-') as folder:
        result = subprocess.run(['/usr/bin/gpg', '--no-options', '--batch', '--homedir', folder,
                                 '--dearmor'], input=key.read_bytes(), capture_output=True, timeout=30)
        if result.returncode:
            raise UpdateError('The pinned KeePassXC release key could not be read.')
        ring = Path(folder) / 'release.gpg'
        ring.write_bytes(result.stdout)
        result = subprocess.run(['/usr/bin/gpgv', '--homedir', folder, '--keyring', str(ring),
                                 '--status-fd', '1', str(signature), str(image)],
                                capture_output=True, text=True, timeout=60)
        valid = [line.split() for line in result.stdout.splitlines()
                 if line.startswith('[GNUPG:] VALIDSIG ')]
        if result.returncode or not any(row[-1] == FINGERPRINT or row[2] == FINGERPRINT for row in valid):
            raise UpdateError('KeePassXC signature verification failed. The existing version has been kept.')
    with image.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_runtime(directory):
    env = dict(PATH='/usr/sbin:/usr/bin:/sbin:/bin', LANG='C', LC_ALL='C',
               LD_LIBRARY_PATH=str(directory / 'usr/lib'))
    for relative in ('usr/bin/keepassxc', 'usr/plugins/platforms/libqxcb.so'):
        result = subprocess.run(['/usr/bin/ldd', str(directory / relative)], env=env,
                                capture_output=True, text=True, timeout=30)
        if result.returncode or 'not found' in result.stdout + result.stderr:
            raise UpdateError('The verified KeePassXC release needs an unavailable system library. Update Debian or use a reviewed Node image. The existing release has been kept.')


def public_tree(directory):
    """Extracted software is public; AppImage extraction uses private directories."""
    for path in [directory, *directory.rglob('*')]:
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)


def install_release(candidate, root=RELEASES, key=KEY):
    """Caller is the root-only maintenance service or disposable ISO builder."""
    version(candidate['version'])
    expected = DOWNLOAD + candidate['version'] + '/' + candidate['name']
    if candidate['url'] != expected or not re.fullmatch(
            r'KeePassXC-' + re.escape(candidate['version']) + r'(?:-[1-9][0-9]{0,2})?-x86_64\.AppImage', candidate['name']):
        raise UpdateError('An unofficial KeePassXC release was refused.')
    if (root / 'current').exists() and version(candidate['version']) < version(current_release(root)['version']):
        raise UpdateError('An automatic KeePassXC downgrade was refused.')
    root.mkdir(parents=True, exist_ok=True, mode=0o755)
    root.chmod(0o755)
    with tempfile.TemporaryDirectory(prefix='.staging-', dir=root) as folder:
        staging = Path(folder)
        image = staging / candidate['name']
        signature = staging / (candidate['name'] + '.sig')
        fetch(candidate['url'], image, 256*1024*1024)
        fetch(candidate['url'] + '.sig', signature, 64*1024)
        digest = verify_image(image, signature, key)
        image.chmod(0o700)
        # Never execute an unverified download. AppImage extraction needs no FUSE.
        subprocess.run([str(image), '--appimage-extract'], cwd=staging, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
        extracted = staging / 'squashfs-root'
        binary = extracted / 'usr/bin/keepassxc'
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise UpdateError('The verified KeePassXC image is incomplete.')
        validate_runtime(extracted)
        icons = sorted(extracted.rglob('keepassxc.png')) + sorted(extracted.rglob('org.keepassxc.KeePassXC.png'))
        icon = next((p for p in icons if p.is_file() and p.resolve().is_relative_to(extracted.resolve())), None)
        if icon is None:
            raise UpdateError('The verified KeePassXC application icon is missing.')
        shutil.copyfile(icon, extracted / 'node-icon.png')
        record = dict(version=candidate['version'], sha256=digest,
                      primary_signer=FINGERPRINT, source=candidate['url'])
        (extracted / 'node-release.json').write_text(json.dumps(record, indent=2) + '\n')
        destination = root / (candidate['version'] + '-' + digest[:16])
        if destination.exists():
            shutil.rmtree(extracted)
        else:
            extracted.rename(destination)
            destination.chmod(0o755)
        public_tree(destination)
        link = staging / 'current'
        link.symlink_to(destination.name)
        os.replace(link, root / 'current')
        fd = os.open(root, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return record
