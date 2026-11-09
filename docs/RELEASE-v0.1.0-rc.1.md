# Bitcoin Core Node v0.1.0-rc.1 — public test release

**Independent BTC Pavao image · Debian GNU/Linux 13 (Trixie), amd64 · Bitcoin Core 32.1**

This is a **release candidate for testing**, not an independently audited security product, and not an official release of Debian or Bitcoin Core. It targets compatible Intel/AMD 64-bit PCs. It does not support Apple Silicon/M-series Macs. Hardware support varies. In particular, Broadcom STA `wl` for some older Intel MacBook Wi-Fi cards is not included, nor is T2-Mac or Secure Boot compatibility certified.

## Verify downloads

Download the ISO, `SHA256SUMS`, `SHA256SUMS.asc`, and `btcpavao-pgp.asc` from this release. Independently establish trust in the PGP signing key fingerprint:

`787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0`

```sh
gpg --import btcpavao-pgp.asc
gpg --fingerprint 787A2AAFB0D119CA0522B2A5B9C99AF8578896D0
gpg --verify SHA256SUMS.asc SHA256SUMS
sha256sum -c SHA256SUMS
```

To verify *only* the downloaded ISO if you have not downloaded every listed file, use `sha256sum -c SHA256SUMS --ignore-missing`. A valid signature authenticates the manifest only if the key is trusted independently; it does not prove code safety or independent reproducibility.

## What the ISO contains

- Installed Debian 13 with the verified unmodified Bitcoin Core 32.1 and KeePassXC 2.8.0 binaries.
- Persistent blockchain storage with pruning support, watch-only wallets, coin control, and a RAM-only PSBT Transfer Folder and Private Workspace.
- Backup and Restore categories for blockchain, watch-only wallets, Core preferences, and portable Node configuration (supported Wi-Fi/NetworkManager profiles, time zone, desktop preferences and managed WireGuard). Backup encryption is optional for the relevant wallet/configuration archives. A login password and signing keys are *not* in a Node configuration export.
- USB browsing and file writing from Node file dialogs, Bitcoin Core, KeePassXC, Editor and Files where the mounted media is writable. Decrypt Files keeps plaintext in verified Private Workspace RAM.
- Optional login password for signing in, without repeated prompts for supported built-in Node administration; GPG and wallet passphrases remain separate.
- Files opens Private Workspace automatically after successful authenticated decryption.
- Home shows Backup and Restore after Private Workspace and before Encrypt Files once the Node has been customized or used, while Settings always retains its own Backup and Restore entry.
- Illustrated Node Guide, Bitcoin Core status dashboard, and verified update-check workflow.

## Install and preserve your data

Flash the ISO to a disposable installation USB; **writing the ISO erases that USB**. Boot the target computer, review keyboard and disk selection, and confirm the installation. **The installer erases the entire selected target internal drive**. Disconnect valuable external backup media before installation and test with disposable wallets first.

This *installed Node* persists Core's blockchain, watch-only data and Node configuration across reboots. Its Private Workspace and PSBT transfer files live in RAM and are lost at shutdown/restart. Watch-only wallets are public data, not a substitute for an offline signing-wallet backup. A blockchain copy does not include wallet signing secrets.

## Release assets and scope

- `bitcoin-core-node-v0.1.0-rc.1-core32.1-amd64.iso` — exact built image (1,321,861,120 bytes).
- `SHA256SUMS`, `SHA256SUMS.asc`, `btcpavao-pgp.asc` — checksums, signature and public key.
- `bitcoin-core-node-v0.1.0-rc.1-source.tar.gz` — matching curated source snapshot at the commit in `SOURCE-COMMIT.txt`. Generated historical validation logs were excluded to avoid publishing private test environment data; no actual program sources were intentionally removed.
- `ACCEPTANCE.json`, `TEST-SCOPE-LIMITS.json`, `BUILD-INFO.json`, `filesystem.packages` — test scope, limits and installed package inventory.

This image passed local source tests, checksum and package checks, and a fresh UEFI VM installation with actual Home customization, cold-boot persistence and GPG recovery. The exact image has **not** been independently rebuilt byte-for-byte or independently security audited. Physical T550/full-mainnet and every possible hardware/USB configuration are not release-certified. See the acceptance and scope documents.

A plain, unencrypted Node configuration backup may expose saved Wi-Fi passwords or managed VPN keys. Treat it as private. The Node is not a general-purpose daily web-browsing computer.

Public release index: https://btcpavao.com/en/bitcoin-core/debian-images/
