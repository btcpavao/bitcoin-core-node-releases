#!/usr/bin/python3
"""Independent Core processes, disposable regtest keys and FAT USB-file exchange.

No host wallet is opened and no P2P networking is enabled. This verifies the
application protocol, not installed BIOS/UEFI or real privacy transport.
"""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import io
import tarfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from rpc import CoreRPC
from state import CORE_SHA256
from wallets import WalletService, WalletError, read_file
import file_crypto, types

parser = argparse.ArgumentParser()
parser.add_argument('--core-bin', type=Path, required=True)
parser.add_argument('--ui', action='store_true')
args = parser.parse_args()
os.umask(0o077)
assert hashlib.sha256((args.core_bin/'bitcoind').read_bytes()).hexdigest() == CORE_SHA256


class Node:
    def __init__(self, directory):
        self.directory = directory; directory.mkdir()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); self.port = sock.getsockname()[1]
        self.rpc = CoreRPC(directory/'regtest/.cookie', self.port)
        self.start()

    def start(self, private=False):
        self.log = (self.directory/'fixture.log').open('ab')
        self.process = subprocess.Popen([str(args.core_bin/'bitcoind'), '-datadir='+str(self.directory),
            '-regtest', '-networkactive=0', '-listen=0', '-server', '-rpcport='+str(self.port),
            '-privatebroadcast='+str(int(private)), *(['-onion=127.0.0.1:1'] if private else []),
            '-dbcache=32', '-debuglogfile=0', '-printtoconsole=1'], stdout=self.log, stderr=self.log)
        for _ in range(200):
            if self.process.poll() is not None:
                raise RuntimeError('Fixture startup failed: '+(self.directory/'fixture.log').read_text()[-1500:])
            try:
                assert self.rpc('getnetworkinfo')['version'] == 320100
                return
            except Exception: time.sleep(.1)
        raise RuntimeError('Fixture startup timed out.')

    def close(self):
        if self.process.poll() is None:
            try: self.rpc('stop')
            except Exception: self.process.terminate()
            self.process.wait(timeout=30)
        self.log.close()


def rejects(fn):
    try: fn()
    except Exception: return
    raise AssertionError('Unsafe or malformed operation unexpectedly succeeded.')


with tempfile.TemporaryDirectory(prefix='node-integration-',dir='/dev/shm') as directory:
    root = Path(directory); offline = Node(root/'offline'); online = None
    try:
        online = Node(root/'online')
        offline.rpc('createwallet', 'vault', False, False, 'test fixture only')
        original = offline.rpc('getnewaddress', 'Native label', 'bech32', wallet='vault')
        offline.rpc('getrawchangeaddress', 'bech32', wallet='vault')
        assert offline.rpc('getwalletinfo', wallet='vault')['unlocked_until'] == 0
        export = root/'watch-only.dat'
        offline.rpc('exportwatchonlywallet', str(export), wallet='vault')
        online.rpc('restorewallet', 'watch', str(export), True)
        service = WalletService(online.rpc, root/'records')
        assert service.watch('watch')['private_keys_enabled'] is False
        assert service.import_status('watch') == 'native'
        assert online.rpc('getaddressinfo', original, wallet='watch')['labels'] == ['Native label']
        for kind in ('legacy', 'p2sh-segwit', 'bech32', 'bech32m'):
            assert online.rpc('getnewaddress', '', kind, wallet='watch') == offline.rpc('getnewaddress', '', kind, wallet='vault')
            assert online.rpc('getrawchangeaddress', kind, wallet='watch') == offline.rpc('getrawchangeaddress', kind, wallet='vault')
        rejects(lambda: online.rpc('listdescriptors', True, wallet='watch'))
        online.rpc('createwallet', 'private-fixture')
        rejects(lambda: service.watch('private-fixture'))
        rejects(lambda: service.receive('private-fixture'))
        assert not hasattr(service, 'import_wallet')
        # Do not silently accept an incomplete receipt from the retired importer.
        (service.directory/'imports').mkdir()
        marker=service.directory/'imports/watch.json'
        marker.write_text('{"status":"incomplete"}')
        rejects(lambda: service.receive('watch'))
        marker.write_text('{"invalid":')
        rejects(lambda: service.receive('watch'))
        marker.unlink()
        print('PASS locked native export/restore, address state, labels, no private keys; native wallets need no receipt; incomplete legacy receipts remain blocked', flush=True)

        funding = service.receive('watch', 'Receiving label', 'bech32')
        assert offline.rpc('getaddressinfo', funding, wallet='vault')['ismine'] is True
        blocks = offline.rpc('generatetoaddress', 101, funding)
        for block in blocks: assert online.rpc('submitblock', offline.rpc('getblock', block, 0)) is None
        online.rpc('syncwithvalidationinterfacequeue')
        assert service.snapshot('watch')['incomplete'] is False
        assert len(service.snapshot('watch')['utxos']) > 0
        offline.rpc('createwallet', 'recipient')
        recipient = offline.rpc('getnewaddress', wallet='recipient')
        proposal = online.rpc('walletcreatefundedpsbt', [], [{recipient:'1.00000000'}], 0,
            {'fee_rate':2,'add_inputs':True}, True, wallet='watch')
        assert online.rpc('decodepsbt',proposal['psbt'])['psbt_version']==2
        assert online.rpc('getrawmempool')==[]
        usb=root/'transfer.img'
        with usb.open('xb') as stream:stream.truncate(16*1024*1024)
        fat=shutil.which('mkfs.fat',path=os.environ.get('PATH','')+':/usr/sbin:/sbin')
        subprocess.run([fat,str(usb)],check=True,capture_output=True)
        unsigned=root/'unsigned.psbt';unsigned.write_bytes(base64.b64decode(proposal['psbt']))
        subprocess.run(['mcopy','-i',str(usb),str(unsigned),'::unsigned.psbt'],check=True)
        received=root/'offline-received.psbt'
        subprocess.run(['mcopy','-i',str(usb),'::unsigned.psbt',str(received)],check=True)
        assert received.read_bytes()==unsigned.read_bytes()
        offline.rpc('walletpassphrase','test fixture only',60,wallet='vault')
        signed=offline.rpc('walletprocesspsbt',base64.b64encode(received.read_bytes()).decode(),True,'ALL',True,False,wallet='vault')
        offline.rpc('walletlock',wallet='vault')
        signed_path=root/'signed.psbt';signed_path.write_bytes(base64.b64decode(signed['psbt']))
        subprocess.run(['mcopy','-i',str(usb),str(signed_path),'::signed.psbt'],check=True)
        returned=root/'returned.psbt'
        subprocess.run(['mcopy','-i',str(usb),'::signed.psbt',str(returned)],check=True)
        final=online.rpc('finalizepsbt',base64.b64encode(returned.read_bytes()).decode())
        assert final['complete'] is True
        decoded=online.rpc('decoderawtransaction',final['hex'])
        assert any(v['scriptPubKey'].get('address')==recipient and v['value']==1 for v in decoded['vout'])
        assert online.rpc('getrawmempool')==[]
        assert online.rpc('testmempoolaccept',[final['hex']])[0]['allowed'] is True
        txid=online.rpc('sendrawtransaction',final['hex'])
        assert txid in online.rpc('getrawmempool')
        assert not online.rpc('getnetworkinfo')['networkactive'] and not offline.rpc('getnetworkinfo')['networkactive']
        assert not any(hasattr(service,name) for name in ('create_transaction','import_signed','broadcast','export_psbt'))
        print('PASS native Core PSBTv2, independent offline signing and FAT exchange, with no custom transaction tools',flush=True)

        native = root/'watch-only-wallet.dat'
        online.rpc('backupwallet', str(native), wallet='watch')
        export_work=root/'export-work';export_work.mkdir(mode=0o700)
        workspace=root/'workspace';workspace.mkdir(mode=0o700)
        policy=types.SimpleNamespace(EXPORT=export_work,PRIVATE=workspace,check_storage=lambda:None,
            file_digest=lambda p:hashlib.sha256(Path(p).read_bytes()).digest(),canonical_path=Path,share_recovered=lambda p:None)
        cipher=root/'native-wallet.gpg'
        file_crypto.create_backup([native],cipher,['disposable backup phrase'],policy=policy)
        rejects(lambda:file_crypto.decrypt_files(cipher,workspace/'wrong',['incorrect'],policy=policy))
        restored=file_crypto.decrypt_files(cipher,workspace/'recovered',['disposable backup phrase'],policy=policy)
        recovered=restored/native.name
        assert recovered.read_bytes()==native.read_bytes()
        online.rpc('restorewallet', 'recovered', str(recovered), True)
        assert service.watch('recovered')['private_keys_enabled'] is False
        assert online.rpc('getaddressinfo', funding, wallet='recovered')['labels'] == ['Receiving label']
        assert service.snapshot('recovered')['incomplete'] is False
        native_name = 'Pavao’s public wallet'
        online.rpc('restorewallet', native_name, str(native), True)
        assert service.watch(native_name)['private_keys_enabled'] is False
        assert service.import_status(native_name) == 'native'
        before={d['desc']:d for d in online.rpc('listdescriptors', False, wallet='watch')['descriptors']}
        after={d['desc']:d for d in online.rpc('listdescriptors', False, wallet=native_name)['descriptors']}
        assert before.keys()==after.keys()
        for desc, previous in before.items():
            current=after[desc]
            assert {k:v for k,v in previous.items() if k!='range'}=={k:v for k,v in current.items() if k!='range'}
            if 'range' in previous:
                # Core may extend its cached lookahead when loading a backup.
                assert current['range'][0]<=previous['range'][0] and current['range'][1]>=previous['range'][1]
        for kind in ('legacy','p2sh-segwit','bech32','bech32m'):
            assert online.rpc('getnewaddress','',kind,wallet='watch')==online.rpc('getnewaddress','',kind,wallet=native_name)
            assert online.rpc('getrawchangeaddress',kind,wallet='watch')==online.rpc('getrawchangeaddress',kind,wallet=native_name)
        print('PASS native Core backup and restore; verified GPG round trip; wrong password rejected; Unicode GUI wallet names', flush=True)
        online.close(); online.start()
        assert 'watch' in online.rpc('listwallets') and 'recovered' in online.rpc('listwallets')
        assert online.rpc('getblockchaininfo')['blocks'] == 101
        assert service.watch('watch')['private_keys_enabled'] is False
        print('PASS daemon restart retains public wallets and validated block history', flush=True)
        if args.ui:
            os.environ['QT_QPA_PLATFORM'] = 'offscreen'; os.environ['HOME'] = str(root)
            from PySide6.QtWidgets import QApplication, QWidget
            from wallet_ui import WalletDialog
            app = QApplication([]); parent = QWidget(); parent.rpc = online.rpc
            for cls in (WalletDialog,):
                dialog = cls(parent); dialog.resize(800, 600); dialog.show()
                deadline = time.monotonic()+10
                while time.monotonic() < deadline:
                    app.processEvents()
                    if dialog.job and not dialog.job.isRunning(): break
                    time.sleep(.02)
                assert dialog.width() <= 800 and dialog.height() <= 600, (cls.__name__, dialog.size())
                assert dialog.job is None or not dialog.job.isRunning()
                dialog.close(); app.processEvents()
            print('PASS native wallet dialogs fit 800x600 with scrollable content', flush=True)
    finally:
        if online is not None: online.close()
        offline.close()
