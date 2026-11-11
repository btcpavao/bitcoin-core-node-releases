#!/usr/bin/python3
"""Populate an owned ISO staging root with a signature-verified upstream release."""
import argparse
from pathlib import Path
import sys

source = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(source / 'app'))
from keepass_updates import install_release, latest_release

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if root == Path('/'):
        parser.error('Use an owned ISO staging root.')
    print(install_release(latest_release(args.version), root / 'opt/keepassxc',
                          source / 'runtime/usr/share/bitcoin-core-node/keepassxc-release-key.asc'))
