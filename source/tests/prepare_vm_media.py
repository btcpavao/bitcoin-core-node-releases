#!/usr/bin/python3
"""Create public-only disposable USB media for installed-service acceptance."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from rpc import CoreRPC
from state import CORE_SHA256

parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--core-bin',type=Path,required=True)
args=parser.parse_args()
assert args.output.absolute().is_relative_to(Path.home()/'node-v1-validation')
assert not args.output.exists()
assert hashlib.sha256((args.core_bin/'bitcoind').read_bytes()).hexdigest()==CORE_SHA256
os.umask(0o077)
with tempfile.TemporaryDirectory(prefix='node-public-fixture-') as directory:
    root=Path(directory);data=root/'core';data.mkdir()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    rpc=CoreRPC(data/'regtest/.cookie',port)
    with (root/'core.log').open('wb') as log:
        process=subprocess.Popen([str(args.core_bin/'bitcoind'),'-datadir='+str(data),'-regtest',
            '-networkactive=0','-listen=0','-server','-rpcport='+str(port),'-dbcache=32'],stdout=log,stderr=log)
    try:
        for _ in range(200):
            try:rpc('getnetworkinfo');break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('Disposable fixture Core did not start.')
        rpc('createwallet','public-test-origin',False,False,'Disposable acceptance keys only')
        public=root/'watch-only.dat'
        rpc('exportwatchonlywallet',str(public),wallet='public-test-origin')
        rpc('restorewallet','verified-public',str(public))
        assert rpc('getwalletinfo',wallet='verified-public')['private_keys_enabled'] is False
        marker=root/'NODE-TEST-ONLY';marker.write_text('disposable QEMU fixture\n')
        with args.output.open('xb') as stream:stream.truncate(32*1024*1024)
        mkfs=shutil.which('mkfs.fat',path=os.environ.get('PATH','')+':/usr/sbin:/sbin')
        subprocess.run([mkfs,'-n','NODE_TEST',str(args.output)],check=True,capture_output=True)
        for source in (public,marker,Path(__file__).with_name('installed_probe.py')):
            subprocess.run(['mcopy','-i',str(args.output),str(source),'::'+source.name],check=True)
        print('Created public-only FAT USB fixture: '+str(args.output))
    finally:
        if process.poll() is None:
            try:rpc('stop')
            except Exception:process.terminate()
            process.wait(timeout=30)
