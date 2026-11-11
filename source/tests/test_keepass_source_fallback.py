"""Offline regressions for the reproduced GitHub HTTP 503 update-check failure."""
import io,json,socket,ssl,sys,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import keepass_updates as k
import system_updates as u

V='2.8.0'; NAME='KeePassXC-2.8.0-1-x86_64.AppImage'; URL=k.DOWNLOAD+V+'/'+NAME
PAGE=f'<a href="{URL}">AppImage</a><a href="{URL}.sig">Signature</a>'.encode()
RECORD=dict(tag_name=V,draft=False,prerelease=False,assets=[dict(name=NAME,browser_download_url=URL)])
class Response(io.BytesIO):
    def __init__(self,data,url):super().__init__(data);self.url=url
class Transport(unittest.TestCase):
    def test_http_503_retries_once_then_official_page_without_weakening_signatures(self):
        calls=[]
        def request(req):
            calls.append(req.full_url)
            if req.full_url.startswith(k.API):raise urllib.error.HTTPError(req.full_url,503,'Service unavailable',{},None)
            return Response(PAGE,k.DOWNLOAD_PAGE)
        with patch.object(k,'_open',side_effect=request),patch.object(k.time,'sleep'):
            value=k.latest_release()
        self.assertEqual(value['url'],URL);self.assertEqual(value['metadata_source'],k.DOWNLOAD_PAGE)
        self.assertEqual(calls,[k.API+'latest',k.API+'latest',k.DOWNLOAD_PAGE]);self.assertIn('HTTP 503',value['metadata_note'])
    def test_rate_limit_uses_other_official_source_without_hammering_api(self):
        failure=urllib.error.HTTPError(k.API+'latest',429,'Rate limit',{'Retry-After':'60'},None)
        with patch.object(k,'_open',side_effect=[failure,Response(PAGE,k.DOWNLOAD_PAGE)]) as op,patch.object(k.time,'sleep') as sleep:
            self.assertEqual(k.latest_release()['version'],V)
        self.assertEqual(op.call_count,2);sleep.assert_not_called()
    def test_retry_after_is_never_retried_early(self):
        failure=urllib.error.HTTPError(k.API+'latest',503,'Unavailable',{'Retry-After':'90'},None)
        with patch.object(k,'_open',side_effect=failure) as op,patch.object(k.time,'sleep') as sleep:
            with self.assertRaisesRegex(k.DownloadError,'HTTP 503'):k.fetch(k.API+'latest')
        self.assertEqual(op.call_count,1);sleep.assert_not_called()
    def test_certificate_failure_does_not_fall_back_or_disable_tls(self):
        failure=urllib.error.URLError(ssl.SSLCertVerificationError(1,'not trusted'))
        with patch.object(k,'_open',side_effect=failure) as op:
            with self.assertRaisesRegex(k.DownloadError,'TLS certificate'):k.latest_release()
        self.assertEqual(op.call_count,1)
    def test_invalid_metadata_not_hidden_by_fallback(self):
        with patch.object(k,'fetch',return_value=json.dumps(dict(RECORD,prerelease=True)).encode()) as fetch:
            with self.assertRaisesRegex(k.UpdateError,'stable'):k.latest_release()
        self.assertEqual(fetch.call_count,1)
    def test_dns_message_names_host_and_not_clock(self):
        failure=urllib.error.URLError(socket.gaierror(-2,'no DNS'))
        with patch.object(k,'_open',side_effect=failure):
            with self.assertRaisesRegex(k.DownloadError,'DNS could not resolve api.github.com') as c:k.fetch(k.API+'latest')
        self.assertNotIn('clock',str(c.exception))
    def test_error_is_not_false_success_when_both_sources_fail(self):
        with patch.object(k,'_open',side_effect=urllib.error.HTTPError(k.API+'latest',503,'Unavailable',{},None)),patch.object(k.time,'sleep'):
            with self.assertRaisesRegex(k.UpdateError,'incomplete'):k.latest_release()
    def test_download_failures_and_oversized_body_never_become_unverified_content(self):
        with patch.object(k,'_open',return_value=Response(b'x'*100,k.DOWNLOAD_PAGE)):
            with self.assertRaisesRegex(k.UpdateError,'size'):k.fetch(k.DOWNLOAD_PAGE,limit=20)
    def test_local_io_failure_is_not_misreported_as_network(self):
        bad=Mock();bad.open.side_effect=OSError('disk full')
        with patch.object(k,'_open',return_value=Response(b'x',URL)):
            with self.assertRaisesRegex(k.UpdateError,'saved locally'):k.fetch(URL,bad)

class Sources(unittest.TestCase):
    def test_trusted_stable_signature_and_architecture(self):
        self.assertEqual(k.website_release(PAGE)['url'],URL)
        for page in [PAGE.replace(b'.AppImage.sig',b'.AppImage.foo'),PAGE.replace(b'x86_64',b'aarch64'),PAGE.replace(b'2.8.0',b'2.9.0-beta1'),PAGE.replace(b'github.com',b'example.invalid')]:
            with self.subTest(page=page),self.assertRaises(k.UpdateError):k.website_release(page)
    def test_ambiguous_versions_and_wrong_requested_version_rejected(self):
        with self.assertRaises(k.UpdateError):k.website_release(PAGE+PAGE.replace(b'2.8.0',b'2.9.0'))
        with self.assertRaises(k.UpdateError):k.website_release(PAGE,'2.7.12')
    def test_https_redirect_allowlist(self):
        for url in ['http://github.com/keepassxreboot/keepassxc/releases/download/a','https://github.com.evil.invalid/a','https://user@github.com/keepassxreboot/keepassxc/releases/download/a','https://github.com/another/repo/a','https://127.0.0.1/file','file:///etc/shadow','https://keepassxc.org/download/?other=1']:
            self.assertFalse(k.trusted_url(url),url)
        self.assertTrue(k.trusted_url(URL));self.assertTrue(k.trusted_url(k.DOWNLOAD_PAGE))
        self.assertTrue(k.trusted_url('https://release-assets.githubusercontent.com/github-production-release-asset/a?token=public-asset'))
    def test_debian_findings_retained_on_failed_keepass_check_but_install_blocked(self):
        writes=[]
        with tempfile.TemporaryDirectory() as td,patch.object(u,'LOCK',Path(td)/'lock'),patch.object(u.os,'geteuid',return_value=0),patch.object(u,'command'),patch.object(u,'plan',return_value=[dict(name='sample',previous='1',version='2')]),patch.object(u,'current_release',return_value=dict(version=V,source=URL)),patch.object(u,'latest_release',side_effect=k.UpdateError('Both official sources failed')),patch.object(u,'write_status',side_effect=lambda **kw:writes.append(kw)),patch.object(u,'install_release') as install:
            with self.assertRaises(k.UpdateError):u.perform('install')
            install.assert_not_called()
        last=writes[-1];self.assertEqual(last['stage'],'error');self.assertFalse(last['updates_available']);self.assertFalse(last['check_complete']);self.assertEqual(len(last['packages']),1)
    def test_older_record_never_claims_up_to_date(self):
        with tempfile.TemporaryDirectory() as td,patch.object(u,'LOCK',Path(td)/'lock'),patch.object(u.os,'geteuid',return_value=0),patch.object(u,'command'),patch.object(u,'plan',return_value=[]),patch.object(u,'current_release',return_value=dict(version='2.8.0',source=URL)),patch.object(u,'latest_release',return_value=dict(version='2.7.12',url=URL)),patch.object(u,'write_status'):
            with self.assertRaisesRegex(k.UpdateError,'older'):u.perform('check')

if __name__=='__main__':unittest.main()
