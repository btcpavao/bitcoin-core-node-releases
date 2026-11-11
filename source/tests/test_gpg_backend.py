"""Real stock GPG corruption tests plus explicitly synthetic failure fixtures."""
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('gpg_backend', ROOT/'app/gpg_backend.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
FAKE = ROOT/'tests/fakegpg.py'


class Cancelled(Exception): pass


class GPGTests(unittest.TestCase):
    def setUp(self):
        # Fresh checkouts may inherit a group-writable umask. Keep the synthetic
        # executable private, as the production executable check requires.
        self.executable_temp = tempfile.TemporaryDirectory(prefix='.fakegpg-', dir=ROOT/'tests')
        self.fake = Path(self.executable_temp.name)/'fakegpg.py'
        self.fake.write_bytes(FAKE.read_bytes()); self.fake.chmod(0o500)
        self.temp = tempfile.TemporaryDirectory(prefix='vault-gpg-unit-', dir='/dev/shm')
        self.root = Path(self.temp.name)
        self.source = self.root/'synthetic wallet.dat'
        self.payload = b'Only synthetic wallet snapshot\0\n'+os.urandom(128*1024)
        self.source.write_bytes(self.payload)
        self.password = 'six random amber basil cedar delta'
        self.cipher = self.root/'backup.gpg'; self.recovered = self.root/'recovered.dat'

    def tearDown(self):
        self.temp.cleanup()
        self.executable_temp.cleanup()

    def encrypt(self, password=None, **kw):
        return b.encrypt_file(self.source, self.cipher, password or self.password,
                              ram_root=self.root, **kw)

    def decrypt(self, source=None, password=None, **kw):
        return b.decrypt_file(source or self.cipher, self.recovered, password or self.password,
                              ram_root=self.root, **kw)

    def assert_clean_failure(self):
        self.assertFalse(self.recovered.exists())
        self.assertFalse(self.cipher.exists())
        self.assertEqual(list(self.root.glob('.vault-gpg-*')), [])

    def test_real_roundtrip_binary_mdc_and_original_unchanged(self):
        self.assertEqual(self.encrypt(), 'AES256-MDC')
        self.assertFalse(self.cipher.read_bytes().startswith(b'-----BEGIN'))
        self.assertNotIn(self.source.name.encode(), self.cipher.read_bytes())
        self.assertEqual(self.decrypt(), 'AES256-MDC')
        self.assertEqual(self.recovered.read_bytes(), self.payload)
        self.assertEqual(self.source.read_bytes(), self.payload)
        self.assertEqual(stat.S_IMODE(self.cipher.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.recovered.stat().st_mode), 0o600)
        self.assertEqual(list(self.root.glob('.vault-gpg-*')), [])

    def test_real_unicode_whitespace_six_and_eight_words(self):
        for phrase in ('  žuti čamac 密碼 Unicode space  ',
                       'amber basil cedar delta ember forest',
                       'amber basil cedar delta ember forest garden harbor'):
            with self.subTest(words=phrase.count(' ')):
                self.encrypt(phrase); self.decrypt(password=phrase)
                self.assertEqual(self.recovered.read_bytes(), self.payload)
                self.cipher.unlink(); self.recovered.unlink()

    def test_real_wrong_password_cleans_provisional_plaintext(self):
        self.encrypt()
        with self.assertRaises(b.GPGError) as caught: self.decrypt(password='wrong synthetic password')
        self.assertNotIn(self.password, str(caught.exception))
        self.assertFalse(self.recovered.exists())
        self.assertEqual(list(self.root.glob('.vault-gpg-*')), [])

    def test_real_corruption_and_truncation(self):
        self.encrypt(); original = self.cipher.read_bytes()
        variants = {'tail':original[:-1], 'half':original[:len(original)//2], 'empty':b''}
        for name, offset in [('middle', len(original)//2), ('last', len(original)-1)]:
            altered = bytearray(original); altered[offset] ^= 1; variants[name] = bytes(altered)
        for name, data in variants.items():
            with self.subTest(case=name):
                damaged=self.root/(name+'.gpg'); damaged.write_bytes(data)
                with self.assertRaises(b.GPGError): self.decrypt(source=damaged)
                self.assertFalse(self.recovered.exists())
                self.assertEqual(list(self.root.glob('.vault-gpg-*')), [])
        self.assertEqual(self.source.read_bytes(), self.payload)

    def _stock_create(self, flags, source=None):
        with tempfile.TemporaryDirectory(dir=self.root) as td:
            fd, writer=os.pipe()
            try:
                os.write(writer, self.password.encode()+b'\n');os.close(writer);writer=None
                result=subprocess.run(['/usr/bin/gpg','--no-options','--homedir',td,'--no-autostart',
                    '--disable-dirmngr','--batch','--no-tty','--no-symkey-cache','--pinentry-mode','loopback',
                    '--s2k-mode','3','--s2k-digest-algo','SHA256','--s2k-count','65011712',
                    '--passphrase-fd',str(fd),'--set-filename','','--output',str(self.cipher),
                    *flags,'--',str(source or self.source)], pass_fds=(fd,), capture_output=True)
                self.assertEqual(result.returncode,0)
            finally:
                os.close(fd)
                if writer is not None:os.close(writer)

    def test_real_plaintext_openpgp_packet_not_encrypted(self):
        self._stock_create(['--store'])
        with self.assertRaises(b.GPGError): self.decrypt()
        self.assertFalse(self.recovered.exists())

    def test_real_aes256_mdc_recovery_supported(self):
        self._stock_create(['--rfc4880','--cipher-algo','AES256','--no-compress','--symmetric'])
        self.assertEqual(self.decrypt(),'AES256-MDC')
        self.assertEqual(self.recovered.read_bytes(),self.payload)

    def test_real_other_cipher_rejected(self):
        self._stock_create(['--force-ocb','--cipher-algo','AES128','--symmetric'])
        with self.assertRaises(b.GPGError):self.decrypt()
        self.assertFalse(self.recovered.exists())

    def test_real_extra_packets_or_garbage_rejected(self):
        self.encrypt(); original=self.cipher.read_bytes()
        for name,data in [('twice',original+original),('garbage',original+b'not OpenPGP')]:
            with self.subTest(case=name):
                source=self.root/(name+'.gpg');source.write_bytes(data)
                with self.assertRaises(b.GPGError):self.decrypt(source=source)
                self.assertFalse(self.recovered.exists())

    def test_empty_control_oversize_and_invalid_unicode_passwords(self):
        for phrase in ('','\0','line\nbreak','line\rbreak','tab\tphrase','x'*513,'\ud800'):
            with self.subTest(kind=repr(phrase[:4])):
                with self.assertRaises(b.GPGError):
                    b.encrypt_file(self.source,self.cipher,phrase,ram_root=self.root)
                self.assert_clean_failure()

    def test_missing_input_and_executable(self):
        with self.assertRaises(b.GPGError):
            b.encrypt_file(self.root/'missing',self.cipher,self.password,ram_root=self.root)
        self.assert_clean_failure()
        with self.assertRaises(b.GPGError):self.encrypt(executable='/not/a/gpg')
        self.assert_clean_failure()
        with self.assertRaises(b.GPGError):self.encrypt(executable='gpg')
        self.assert_clean_failure()

    def test_existing_file_and_symlink_destinations_never_overwritten(self):
        self.cipher.write_bytes(b'sentinel')
        with self.assertRaises(b.GPGError):self.encrypt()
        self.assertEqual(self.cipher.read_bytes(),b'sentinel')
        self.cipher.unlink();self.cipher.symlink_to(self.source)
        with self.assertRaises(b.GPGError):self.encrypt()
        self.assertEqual(self.source.read_bytes(),self.payload)

    def test_decrypt_existing_destination_preserved(self):
        self.encrypt(); self.recovered.write_bytes(b'existing result')
        with self.assertRaises(b.GPGError):self.decrypt()
        self.assertEqual(self.recovered.read_bytes(),b'existing result')

    def test_single_regular_input_only(self):
        directory=self.root/'folder';directory.mkdir()
        link=self.root/'link';link.symlink_to(self.source)
        fifo=self.root/'fifo';os.mkfifo(fifo)
        for source in (directory,link,fifo):
            with self.subTest(kind=source.name):
                with self.assertRaises(b.GPGError):b.encrypt_file(source,self.cipher,self.password,ram_root=self.root)
                self.assert_clean_failure()

    def test_control_filename_rejected_and_shell_syntax_safe(self):
        bad=self.root/'bad\nfilename';bad.write_bytes(self.payload)
        with self.assertRaises(b.GPGError):b.encrypt_file(bad,self.cipher,self.password,ram_root=self.root)
        special=self.root/'-wallet $(touch FORBIDDEN);.dat';special.write_bytes(self.payload)
        b.encrypt_file(special,self.cipher,self.password,ram_root=self.root)
        self.decrypt();self.assertEqual(self.recovered.read_bytes(),self.payload)
        self.assertFalse((self.root/'FORBIDDEN').exists())

    def test_ram_directory_and_destination_boundaries(self):
        self.root.chmod(0o755)
        try:
            with self.assertRaises(b.GPGError):self.encrypt()
        finally:self.root.chmod(0o700)
        # CI's unprivileged account cannot write to the source checkout.
        disk_root = Path(os.environ.get('VAULT_TEST_DISK_ROOT', str(ROOT)))
        with tempfile.TemporaryDirectory(dir=disk_root) as disk:
            with self.assertRaises(b.GPGError):
                b.encrypt_file(self.source,Path(disk)/'never-created',self.password,ram_root=disk)
            self.assertEqual(list(Path(disk).iterdir()),[])
        with tempfile.TemporaryDirectory(dir='/dev/shm') as other:
            with self.assertRaises(b.GPGError):
                b.encrypt_file(self.source,Path(other)/'outside',self.password,ram_root=self.root)
            self.assertEqual(list(Path(other).iterdir()),[])

    @unittest.skipIf(os.geteuid()==0,'permission denial requires unprivileged test execution')
    def test_unreadable_file(self):
        self.source.chmod(0)
        with self.assertRaises(b.GPGError):self.encrypt()
        self.assert_clean_failure()

    def test_source_mutation_detected_no_result(self):
        class Mutate:
            mutated=False
            def check(inner):
                if self.cipher.exists() and not inner.mutated:
                    self.source.write_bytes(b'changed synthetic input');inner.mutated=True
        with self.assertRaises(b.GPGError):self.encrypt(progress=Mutate())
        self.assert_clean_failure()

    def test_no_secret_in_argv_environment_or_files(self):
        seen=[];real=b.subprocess.Popen
        def observe(args,**kw):
            self.assertNotIn(self.password,repr(args));self.assertNotIn(self.password,repr(kw['env']))
            self.assertEqual(os.readlink('/proc/self/fd/'+str(kw['pass_fds'][0])).split(':')[0],'pipe')
            self.assertTrue(kw['start_new_session']);self.assertEqual(kw['stderr'],subprocess.DEVNULL)
            self.assertNotIn('VAULT_TEST_SECRET_ENV',kw['env']);seen.append(True)
            return real(args,**kw)
        with patch.dict(os.environ,{'VAULT_TEST_SECRET_ENV':self.password}),patch.object(b.subprocess,'Popen',observe):
            self.encrypt();self.decrypt()
        self.assertGreaterEqual(len(seen),3)
        for path in self.root.rglob('*'):
            if path.is_file():self.assertNotIn(self.password.encode(),path.read_bytes())

    def test_synthetic_status_false_success_rejected(self):
        for mode in ('WRONG_PROFILE','MISSING_AUTH','LITERAL_ONLY','MULTIPLE','FAILURE_EXIT_ZERO',
                     'ERROR_EXIT_ZERO','ERRMDC_EXIT_ZERO','NODATA_EXIT_ZERO','INCOMPLETE_STATUS','NONZERO_WITH_SUCCESS',
                     'GOODMDC_DUPLICATE','GOODMDC_WRONG_POSITION','MISSING_INFO'):
            with self.subTest(mode=mode):
                source=self.root/'synthetic-input.gpg';source.write_bytes(mode.encode())
                with self.assertRaises(b.GPGError):self.decrypt(source=source,executable=self.fake)
                self.assertFalse(self.recovered.exists())
                self.assertEqual(list(self.root.glob('.vault-gpg-*')),[])

    def test_synthetic_wrong_creation_profile_no_fallback(self):
        with self.assertRaises(b.GPGError):self.encrypt(executable=self.fake)
        self.assert_clean_failure()
        proof=json.loads((self.root/'fixture-proof.json').read_text())
        self.assertIn('--decrypt',proof['argv']);self.assertNotIn('--force-ocb',proof['argv'])
        self.assertTrue(proof['secret_absent_argv'] and proof['secret_absent_env'] and proof['passphrase_fd_is_pipe'])
        self.assertEqual(proof['core_limit'],0)

    def test_reaped_process_never_signalled_on_status_rejection(self):
        source=self.root/'fake.gpg';source.write_bytes(b'ERROR_EXIT_ZERO')
        with patch.object(b.os,'killpg',side_effect=AssertionError('stale PGID signal')):
            with self.assertRaises(b.GPGError):self.decrypt(source=source,executable=self.fake)
        self.assertFalse(self.recovered.exists())

    def test_synthetic_obsolete_goodmdc_optional_only_with_complete_authentication(self):
        source=self.root/'fake.gpg';source.write_bytes(b'GOODMDC_ABSENT')
        self.assertEqual(self.decrypt(source=source,executable=self.fake),'AES256-OCB')
        self.assertEqual(self.recovered.read_bytes(),b'provisional synthetic plaintext')
        # Simulated protocol acceptance is distinct from the real encryption tests.
        self.recovered.unlink()
        required=[b'BEGIN_DECRYPTION',b'DECRYPTION_INFO 0 9 2',b'PLAINTEXT 62 0 ',
                  b'DECRYPTION_OKAY',b'END_DECRYPTION']
        for missing in range(len(required)):
            status=b._Status()
            for event in required[:missing]+required[missing+1:]:status.line(b'[GNUPG:] '+event)
            with self.assertRaises(b.GPGError):status.finish('decrypt')
        for bad in (b'DECRYPTION_INFO 0 7 2',b'DECRYPTION_INFO 0 9 1',b'DECRYPTION_INFO 0 9 0'):
            status=b._Status()
            for event in required:status.line(b'[GNUPG:] '+(bad if event.startswith(b'DECRYPTION_INFO') else event))
            with self.assertRaises(b.GPGError):status.finish('decrypt')

    def _hung_operation(self,cancel):
        # Reap this fixture's orphan descendants in the test process, not production.
        libc=ctypes.CDLL(None);previous=ctypes.c_int()
        self.assertEqual(libc.prctl(37,ctypes.byref(previous),0,0,0),0)
        self.assertEqual(libc.prctl(36,1,0,0,0),0)
        source=self.root/'hanging.gpg';source.write_bytes(b'HANG')
        class Progress:
            def check(inner):
                if cancel and (self.root/'fixture-proof.json').exists():raise Cancelled()
        try:
            with patch.object(b,'OPERATION_TIMEOUT',.5):
                with self.assertRaises(Cancelled if cancel else b.GPGError):
                    self.decrypt(source=source,progress=Progress(),executable=self.fake)
            self.assertFalse(self.recovered.exists());self.assertEqual(list(self.root.glob('.vault-gpg-*')),[])
            proof=json.loads((self.root/'fixture-proof.json').read_text())
            child=proof['child_pid'];os.waitpid(child,0)
            for pid in (proof['pid'],child):
                with self.assertRaises(ProcessLookupError):os.kill(pid,0)
        finally:libc.prctl(36,previous.value,0,0,0)

    def test_cancel_kills_owned_group_and_removes_partial(self):self._hung_operation(True)
    def test_timeout_kills_owned_group_and_removes_partial(self):self._hung_operation(False)


if __name__=='__main__':unittest.main(verbosity=2)
