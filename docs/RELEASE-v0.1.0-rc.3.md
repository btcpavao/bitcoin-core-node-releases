# Bitcoin Core Node v0.1.0-rc.3

Installable Debian 13 for amd64 with Bitcoin Core 32.1 and KeePassXC 2.8.0. Tested on a ThinkPad T550.

- Manage regular and watch-only wallets from Wallets. Closing a wallet in Bitcoin Core preserves access to wallet management.
- Updated blockchain backup and restore, including wallet recovery on pruned nodes. The desktop shows a solid sync progress bar and disk space in GB.
- The Debian Home button returns to the desktop with Wallets or Node Guide open. Crowded taskbar buttons switch to icons with hover titles.
- Num Lock starts enabled at login. Debian packages are pinned to the 19 November 2026 snapshot for this build.
- The release includes the package inventories, filesystem hashes, prepared source and pinned build recipe. The ISO was checked for BIOS and UEFI boot and tested through a UEFI installation.

Download the ISO, SHA256SUMS, SHA256SUMS.asc and btcpavao-pgp.asc. Confirm the full publisher fingerprint independently, verify the signature, then check the ISO against its entry. The separate .iso.asc signature also verifies the ISO directly.

Publisher fingerprint: 787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0

ISO SHA-256: 39e9b5b76dce7d9854989365d389caa50d55f0b0c5654602eafc7e12904b6675

[Verification and reproducible-build instructions](https://github.com/btcpavao/bitcoin-core-node-releases/blob/v0.1.0-rc.3/docs/REBUILD.md) · [GitHub rebuild and comparison](https://github.com/btcpavao/bitcoin-core-node-releases/actions/runs/44714236174)
