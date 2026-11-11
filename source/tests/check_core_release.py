#!/usr/bin/python3
"""Check active release pins, runtime paths and native-only wallet entry points."""
import ast, hashlib, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'app'))
from state import CORE_SHA256,CORE_GUI_SHA256
from upgrades import BASELINE
assert BASELINE['version']=='32.1' and BASELINE['path']=='/opt/bitcoin-core/32.1'
assert CORE_SHA256=='580ac61190154da31aac3f82d13c4254ef453d70e1bf2c39d338dac5129c92ac'
assert CORE_GUI_SHA256=='d43632a3e54dfb181ba045db2a5b1ec2396a1acdda010e3b6d07b2e21c69c183'
assert not (root/'app/public_descriptors.py').exists()
for f in ['app/ui.py','app/wallet_ui.py','app/wallets.py']:
 source=(root/f).read_text();tree=ast.parse(source)
 assert not any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in ('import_wallet','preview_import','retry_import','public_export','import_from_vault','create_transaction','import_signed','export_psbt','wallet_snapshot') for n in ast.walk(tree)),f
assert 'Import Watch-Only Wallet' not in (root/'app/ui.py').read_text()
assert 'File → Restore Wallet' in (root/'app/guide_ui.py').read_text()
assert '/var/lib/bitcoin-core-node/transfer' in (root/'runtime/etc/systemd/system/bitcoin-core-node.service').read_text()
print('PASS Core 32.1 pins, native Guide, public file bridge and removal of custom import/export')


assert not (root/'app/recovery.py').exists()
assert all(title not in (root/'app/ui.py').read_text() for title in ('Create Transaction','Import Signed PSBT','Wallet Backup'))
assert 'wallet-snapshot' not in (root/'runtime/usr/libexec/core-node-admin').read_text()
