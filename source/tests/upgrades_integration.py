#!/usr/bin/python3
"""Verify the genuine pinned upstream archive and reject altered release inputs."""
import argparse
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from upgrades import inspect_bundle, version
from wallets import WalletError
from state import CORE_SHA256

parser=argparse.ArgumentParser();parser.add_argument('--archive',type=Path,required=True);args=parser.parse_args()
project=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='node-upgrade-check-') as folder:
    root=Path(folder)
    for name in ['SHA256SUMS','SHA256SUMS.asc']:shutil.copyfile(project/'provenance/32.1'/name,root/name)
    archive=root/'bitcoin-32.1-x86_64-linux-gnu.tar.gz';shutil.copyfile(args.archive,archive)
    result=inspect_bundle(root,'32.1')
    assert result['binary_sha256']==CORE_SHA256 and len(result['signers'])>=2
    # This baseline has eight cryptographic signatures; expired keys are not
    # counted toward the currently-valid two-signer maintenance threshold.
    assert '9EDAFF80E080659604F4A76B2EBB056FD847F8A7' not in result['signers']
    assert hashlib.sha256(result['files']['bin/bitcoind'][0]).hexdigest()==CORE_SHA256
    del result
    print('PASS genuine Core archive, multiple current release signers, expired-key exclusion and pinned daemon bytes',flush=True)
    def reject(fn):
        try:fn()
        except (WalletError,ValueError):return
        raise AssertionError('Changed release input was accepted.')
    original=(root/'SHA256SUMS').read_bytes()
    (root/'SHA256SUMS').write_bytes(original+b'changed signed document\n')
    reject(lambda:inspect_bundle(root,'32.1'));(root/'SHA256SUMS').write_bytes(original)
    original=(root/'SHA256SUMS.asc').read_bytes();(root/'SHA256SUMS.asc').write_bytes(b'not a signature')
    reject(lambda:inspect_bundle(root,'32.1'));(root/'SHA256SUMS.asc').write_bytes(original)
    with archive.open('r+b') as stream:
        first=stream.read(1);stream.seek(0);stream.write(bytes([first[0]^1]))
    reject(lambda:inspect_bundle(root,'32.1'))
    reject(lambda:inspect_bundle(root,'33.0'))
    reject(lambda:version('../32.1'))
    print('PASS altered signed checksums, invalid signatures, altered archive, unsupported major and path rejection',flush=True)
