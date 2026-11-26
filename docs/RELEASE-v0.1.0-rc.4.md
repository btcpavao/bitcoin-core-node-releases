# Bitcoin Core Node v0.1.0-rc.4

Debian 13 for amd64 with Bitcoin Core 32.1. This release publishes the exact local image approved by the project owner on 26 November 2026: 1,800,142,848 bytes, SHA-256 `b25093180bb9b8f57adf2163634be3473fbc0f5163e9fcb05008651f2e0f6da7`. The approved ISO was not rebuilt for publication.

## Changes in this candidate

- The installer preserves the explicitly chosen installation disk through Continue and Review. The correction addresses the reported larger-disk selection being replaced by the smaller disk. Existing disk-identity, plan and confirmation guards remain in place.
- Wi-Fi password prompts use network-neutral guidance instead of asking for an iPhone hotspot password for every network.
- Private Workspace is the single temporary RAM workspace. The separate PSBT Transfer Folder has been removed.
- Backup and Restore remains in Settings; its duplicate desktop launcher is removed.
- Home no longer displays the additional storage/pruning explanation below “Bitcoin Core online node environment.”
- The blockchain-storage hover uses the same padded popup and presentation as Date & Time. Bundled Guide text follows the updated interface.

## Verification and PGP status

**PGP signatures are published and verified.** The publisher signed the frozen `SHA256SUMS` manifest and the exact ISO on 26 November 2026. Both detached signatures were independently verified against the established public fingerprint before upload. Download `SHA256SUMS.asc`, the optional direct ISO signature and `btcpavao-pgp.asc` from this release. The ISO and original checksum manifest are unchanged.

Expected publisher fingerprint: `787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0`.

The exact ISO is `bitcoin-core-node-v0.1.0-rc.4-core32.1-amd64.iso`. To compare a downloaded copy against this checksum, with `SHA256SUMS` in the same directory:

```sh
sha256sum --check --ignore-missing SHA256SUMS
```

After confirming the publisher fingerprint independently:

```sh
gpg --import btcpavao-pgp.asc
gpg --fingerprint 787A2AAFB0D119CA0522B2A5B9C99AF8578896D0
gpg --verify SHA256SUMS.asc SHA256SUMS
sha256sum --check --ignore-missing SHA256SUMS
```

The optional direct ISO signature is named `bitcoin-core-node-v0.1.0-rc.4-core32.1-amd64.iso.asc`.

## Source and evidence

`bitcoin-core-node-v0.1.0-rc.4-source.tar.gz` is the tracked source archived at `8eae47cb3c2c67c7365dcfcc25af44cd5048baf3`; `SOURCE-COMMIT.txt` records that identity. This commit was made after the tested build. The original build used source base `7d2a3d95dee0861b52c25420d3c5530463183cd6` plus the exact retained UI/Guide patch. `SOURCE-PROVENANCE.json` separates these identities and records all six final runtime hashes.

The recipe archive preserves the native/base recipe, final UI overlay driver and patch. It depends on the recorded local base image and metadata; it is not a demonstrated self-contained fresh rebuild of rc.4. The matching Calamares `3.3.14-1+corenode6diskselect1` corresponding source is included separately.

`BUILD-INFO.json`, `ACCEPTANCE.json`, `TEST-SCOPE-LIMITS.json` and `filesystem.packages` describe the build and verification. The exact final image received targeted source/Qt preview/content checks, followed by the owner's approval. BIOS two-disk installation and UEFI selection evidence applies to its preceding `254a0ef3…` base image. No new full test suite or VM installation was run for the six-file final UI overlay. RC3's two byte-identical GitHub rebuilds remain historical evidence for RC3 only.

This is an ISO replacement release, not an automatic update to installed Nodes. Normal Node data persists on disk; Private Workspace is temporary RAM storage. Installation writes to the selected destination disk. Full-mainnet operation, every hardware configuration, Secure Boot and independent security review are not established by this release's scoped evidence.

[Download page](https://btcpavao.com/en/bitcoin-core/debian-images/) · [Previous signed RC3 release](https://github.com/btcpavao/bitcoin-core-node-releases/releases/tag/v0.1.0-rc.3)
