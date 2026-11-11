#!/usr/bin/python3
"""Real Core regtest, generated disposable wallets only; never accepts a datadir."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from wallet_startup import clean_startup
from wallet_delete import wipe_directory


def main(core):
    core=Path(core).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='node-wallet-regtest-') as td:
        data=Path(td);wallets=data/'wallets';wallets.mkdir()
        settings=data/'settings.json'
        with socket.socket() as socket_:
            socket_.bind(('127.0.0.1',0));port=socket_.getsockname()[1]
        common=['-regtest','-datadir='+str(data),'-rpcport='+str(port)]
        server=['-walletdir='+str(wallets),'-settings='+str(settings)]
        process=None
        log=(data/'process.log').open('w')

        def rpc(method,*args,wallet=None):
            cmd=[str(core/'bitcoin-cli'),*common]
            if wallet is not None:cmd.append('-rpcwallet='+wallet)
            result=subprocess.run([*cmd,method,*args],capture_output=True,text=True,timeout=20)
            if result.returncode:raise RuntimeError(result.stderr)
            text=result.stdout.strip()
            try:return json.loads(text)
            except ValueError:return text

        def start():
            nonlocal process
            process=subprocess.Popen([str(core/'bitcoind'),*common,*server,'-server','-listen=0',
                                      '-connect=0','-dnsseed=0','-fixedseeds=0'],stdout=log,stderr=log)
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('Core exited during regtest startup')
                try:rpc('getblockchaininfo');return
                except RuntimeError:time.sleep(0.1)
            raise RuntimeError('Core did not become ready')

        def stop():
            rpc('stop');assert process.wait(timeout=30)==0

        try:
            start()
            rpc('createwallet','remove','false','false','','false','true','true')
            rpc('createwallet','watch-only','true','true','','false','true','true')
            descriptor=rpc('getdescriptorinfo',
                           'wpkh(0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798)')['descriptor']
            result=rpc('importdescriptors',json.dumps([{'desc':descriptor,'timestamp':'now'}]),wallet='watch-only')
            assert result[0]['success'],result
            original=rpc('listdescriptors',wallet='watch-only')['descriptors']
            assert set(rpc('listwallets'))=={'remove','watch-only'}
            # The selected wallet is loaded at the moment shutdown starts.
            stop()
            clean_startup(settings,wallets,os.getuid(),selected=['remove'])
            wipe_directory('remove',wallets,os.getuid())
            start()
            assert rpc('listwallets')==['watch-only']
            assert rpc('getwalletinfo',wallet='watch-only')['private_keys_enabled'] is False
            assert rpc('listdescriptors',wallet='watch-only')['descriptors']==original
            assert 'remove' not in json.loads(settings.read_text()).get('wallet',[])
            stop()
            # Reproduce manual deletion after Core has closed, without editing
            # its settings first. Startup repair must forget just that folder.
            start();rpc('createwallet','manual','false','false','','false','true','true');stop()
            shutil.rmtree(wallets/'manual')
            assert 'manual' in json.loads(settings.read_text())['wallet']
            assert clean_startup(settings,wallets,os.getuid(),missing=True)==['manual']
            start()
            assert rpc('listwallets')==['watch-only']
            assert rpc('listdescriptors',wallet='watch-only')['descriptors']==original
            stop()
            debug=(data/'regtest/debug.log').read_text()
            assert "Skipping wallet path that doesn't exist" not in debug
            assert 'Failed to load database path' not in debug
            print('REAL CORE REGTEST PASSED: loaded deletion, stale startup repair, watch-only descriptors preserved')
        finally:
            if process is not None and process.poll() is None:
                process.terminate();process.wait(timeout=30)
            log.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--core-bin',required=True)
    main(parser.parse_args().core_bin)
