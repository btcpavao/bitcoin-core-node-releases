# Bitcoin Core Node — Debian image releases

An independently developed online Bitcoin Core Node environment for ordinary amd64 Intel/AMD computers, based on Debian GNU/Linux 13 and the official Bitcoin Core 32.1 binaries. Designed to pair with a separate offline signer such as [Bitcoin Core Vault](https://github.com/btcpavao/bitcoin-core-vault-releases).

**Current test release candidate: v0.1.0-rc.1.** [Release assets, ISO, checksums and source](https://github.com/btcpavao/bitcoin-core-node-releases/releases/tag/v0.1.0-rc.1). This is not an official Bitcoin Core or Debian release, nor an independently audited or independently reproducible ISO. Evaluate it on noncritical hardware with disposable wallets.

## Screenshots

Actual Bitcoin Core Node v0.1.0-rc.1 interface, captured at 1280 × 800 in a demonstration session. No personal wallets, credentials or funds are shown. Open an image to see it at full size.

The Node capture is intentionally disconnected from the network. The optional Home backup shortcut is enabled.

### Node Home

![image: Node Home](docs/screenshots/home.png)

The installed Node home. The optional Backup and Restore shortcut is enabled after customization.

### Node Settings

![image: Node Settings](docs/screenshots/settings.png)

Network, devices, backups, optional login password and software updates.

### Node Guide

![image: Node Guide](docs/screenshots/guide.png)

Built-in guidance for validation, watch-only wallets and PSBT workflows.

[Capture details](docs/screenshots/CAPTURE.json) · [Website gallery](https://btcpavao.com/en/bitcoin-core/debian-images/#online-node)

## How to verify downloads

Download the ISO, `SHA256SUMS`, `SHA256SUMS.asc`, and `btcpavao-pgp.asc` from the same release. Independently validate that the signing key's fingerprint belongs to this publisher:

`787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0`

```sh
gpg --import btcpavao-pgp.asc
gpg --fingerprint 787A2AAFB0D119CA0522B2A5B9C99AF8578896D0
gpg --verify SHA256SUMS.asc SHA256SUMS
sha256sum -c SHA256SUMS
```

The key and signature arriving together do *not* independently prove identity; compare the fingerprint through an independent trusted channel. If downloading just the ISO and checksum manifest, use `sha256sum -c SHA256SUMS --ignore-missing`.

## What it does

This installed Linux node maintains a persistent blockchain, watch-only wallet data and configuration. Home includes Bitcoin Core, private RAM workspace, optional Home shortcut for Backup and Restore after Node customization, encryption/decryption tools, KeePassXC, Files, Editor and Node Guide. A RAM-only PSBT Transfer Folder supports USB transfer to an offline signer.

Backup categories include blockchain/chainstate, public watch-only wallets, portable Core configuration and supported Node settings (Wi-Fi profiles, date/time and managed WireGuard). USB media are exposed in the file pickers with scoped write access when writable. Decryption output is recovered in RAM and Private Workspace opens after success. An optional desktop login password is not repeatedly requested for the built-in Node operations; it does not encrypt the disk.

**Installation erases the selected target internal disk.** The installed Node is different from the stateless Vault; its private working folders, not its blockchain, are RAM-only. Keep wallet signing keys offline and practice backup restoration before using it with real funds.

## Limitations

- Independent security audit and bit-for-bit reproducible independent build are not established.
- Apple Silicon/M-series Macs are not supported. Secure Boot, Intel Macs with T2 and certain Broadcom Wi-Fi cards are not certified.
- A Node/watch-only backup does not contain signing keys. An unencrypted network-settings backup may reveal saved credentials.
- Full mainnet sync, hardware compatibility and every external disk adapter have not been tested in this exact public release.

The release includes scoped test evidence, package inventory, build/source commit and a curated matching source archive. See [release notes](docs/RELEASE-v0.1.0-rc.1.md) and [third-party notices](THIRD_PARTY_NOTICES.md). Project-local code does not yet have a specified blanket license; upstream packages retain their licenses.

Website download guide: https://btcpavao.com/en/bitcoin-core/debian-images/
