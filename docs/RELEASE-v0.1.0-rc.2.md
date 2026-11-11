# Bitcoin Core Node v0.1.0-rc.2 — Practical Guide & Faster Backups

**Bitcoin Core 32.1 · Debian GNU/Linux 13 Trixie · amd64 (Intel/AMD) · Public test release**

This release contains the **exact local Bitcoin Core Node Practical Guide ISO built on November 10, 2026**, with source commit `0d43a61e82ab1a0ee86a0b916d1215f31f4502e3`. On November 11, the project owner reported successfully testing this version locally. That report is not a substitute for an independent audit, repeatable build, or exhaustive hardware testing. This project is independent of Bitcoin Core and Debian.

## Changes compared with v0.1.0-rc.1

**Practical Node Guide:** A new 19-chapter guide in the same visual style as Vault starts with the complete offline-signing workflow: create/export a watch-only wallet in Vault, restore it on Node, validate the blockchain, generate receiving addresses, create an unsigned PSBT on Node, review/sign offline on Vault, and return the completed transaction to Node for broadcast. Dedicated chapters explain what an unlocked or physically accessible online Node can reveal; optional desktop login and its limits; calculating a pruning/storage budget and handling wallet rescans; and the four different Backup and Restore categories. A standalone HTML copy is provided.

**Backup and Restore export performance:** All four categories (blockchain, watch-only wallet collection, Bitcoin Core configuration, Node configuration) **no longer perform an extra post-copy destination read-back/round-trip verification pass**. Copy, encryption when selected, flush/sync, checksums calculated during writing, error handling and atomic publication still apply. The signed message now says **saved**, not **verified**. For blockchain backup Core stops cleanly and remains stopped until you reopen it.

**Important trade-off:** A successfully saved backup has **not** been read back or recovery-tested. Maintain multiple independent copies and periodically test restoring one on an appropriate trusted installation. The change does **not** disable restore-time checks or GPG authentication. Importing/restoring chainstate still validates the copy and opens it in an isolated Bitcoin Core before activation. The standalone **Encrypt Files** tool continues to do its existing full round-trip verification.

Previous enhancements are retained, including USB file-manager integration, dedicated RAM-only Private Workspace/PSBT Transfer Folder, optional desktop login, Keyboard & Mouse, chain storage capacity meter, status centering, network/updates controls and wallet backup support.

## Download and verify

Download the ISO together with `SHA256SUMS`, `SHA256SUMS.asc`, and `btcpavao-pgp.asc` from **this GitHub Release**. Independently verify the publisher's OpenPGP fingerprint (do not simply trust a key delivered alongside its signature):

`787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0`

```bash
gpg --import btcpavao-pgp.asc
gpg --fingerprint 787A2AAFB0D119CA0522B2A5B9C99AF8578896D0
gpg --verify SHA256SUMS.asc SHA256SUMS
sha256sum -c SHA256SUMS
```

If only the ISO was downloaded, `sha256sum -c SHA256SUMS --ignore-missing` verifies the files you have. The signature authenticates the checksum manifest once you establish trust in the signing key: it is not a guarantee that all software is secure.

## Installation and security scope

The ISO installs an online Node on compatible 64-bit Intel/AMD computers. **The installer erases the entire selected destination disk**; disconnect valuable media first and choose the target carefully. Apple Silicon/M-series Macs are not supported; Secure Boot, T2 Macs and every wireless adapter are not certified.

Node's blockchain, watch-only wallets and ordinary configuration persist on disk. Private Workspace and PSBT Transfer Folder are temporary RAM-only work areas. The optional login password **is not full-disk encryption**. Physical access to the Node's storage may expose watch-only wallet metadata such as balances and transaction history. Keep Bitcoin signing keys and the corresponding Core/GPG backup passphrases offline on Vault.

## Test evidence and files

- `bitcoin-core-node-v0.1.0-rc.2-core32.1-amd64.iso`: exact verified image, 1,321,861,120 bytes.
- `SHA256SUMS`, `SHA256SUMS.asc`, `btcpavao-pgp.asc`: signed checksums and public signing key.
- `bitcoin-core-node-v0.1.0-rc.2-source.tar.gz`, `SOURCE-COMMIT.txt`: curated matching tracked source at the specified commit.
- `ACCEPTANCE.json`, `BUILD-INFO.json`, `TEST-SCOPE-LIMITS.json`, `filesystem.packages`: scope and build/package information.
- `NODE-GUIDE.html`: standalone copy of the bundled 19-chapter guide.
- `THIRD_PARTY_NOTICES.md`: third-party license notices.

Local testing included 485 unit tests (468 passed, 17 skipped), 24 isolated root-operation tests, 76 Guide viewport checks, a clean UEFI installation/reboot without ISO, seven actual disposable backup exports on a synthetic USB, small regtest chainstate export/import, and checks rejecting damaged archives or wrong secrets. The previous BIOS/legacy build path was not rerun for this release. It does **not** demonstrate full-mainnet backup throughput, a bit-for-bit independent reproducible rebuild or independent security audit.

Website: https://btcpavao.com/en/bitcoin-core/debian-images/
