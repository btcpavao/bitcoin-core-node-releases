# Local Core 32.1 Node update

Base: d2c156f (Unicode Wi-Fi/NetworkManager fix). Upstream Bitcoin Core is unchanged.
Native public database export on Vault and File → Restore Wallet on Node replace
custom JSON/GPG-TAR watch-only import/export and portable JSON recovery packages.
Loaded native watch-only descriptor wallets work with balances, receiving addresses,
transaction creation and native/GPG wallet backup without a custom import receipt.
Existing incomplete receipts stay blocked. Native backups do not include pending
PSBT files or the application's transaction proposal records; keep those separately.

## Public file transfer

Core retains its separate unprivileged account and restricted filesystem. Files and
Core expose Public Wallet Transfer at /var/lib/bitcoin-core-node/transfer, group
bitcoin-rpc, mode 2770. The installed-only path service adds group read/write only
to regular single-link files owned by node/bitcoinnode with that group. It never
reads data, follows symlinks, touches nested directories or changes other paths.
This is necessary because Files preserves source permissions even with a default ACL.
Users intentionally place public exports, PSBTs and public backups in that folder.

## Core 32 PSBT compatibility

Core 32 defaults to PSBTv2, whose decodepsbt result has no tx field. The existing
Node proposal protocol explicitly requests PSBTv0 using the supported psbt_version
argument. Core owns all transaction parsing, construction and signing. The saved
proposal fingerprint and exact signed-transaction matching are unchanged. Native
Core GUI PSBT workflows use their own supported versions. Unrelated PSBTv2 files
are refused cleanly by the proposal-specific Import Signed PSBT workflow.

## Validation

Exact local ISO build and VM acceptance results are stored beside the ISO in
/home/pavao/node-local-build-core-32.1-20261029. Historical acceptance reports retain
their original version/image scope; they are not evidence for this build.
Physical T550 validation follows the local tests. No GitHub publication requested.
