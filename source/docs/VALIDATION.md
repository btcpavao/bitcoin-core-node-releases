# Development acceptance record — 19 October 2026

This is the historical acceptance for the images identified below. The current
onboarding revision is recorded in [20 October acceptance](ONBOARDING-VALIDATION.md).

The Bitcoin Core 31.1 development candidate identified below passed the acceptance
checks recorded below. This is a development artifact for review, not a published
stable release. The work does not change stable Vault releases or the earlier
Signer repository. All wallets, keys, disks and transactions used for acceptance
were disposable fixtures; transaction tests used regtest.

## Accepted artifacts

| Artifact | Source and SHA256 |
|---|---|
| Node development ISO | Source `82c2301e1d8f86e6962583bc5072a866ac6f411d`; SHA256 `adae30f3722a93919ead6b6b286c4cda38933f58a1507a3d1088247daff10fa1` |
| Vault integration ISO | Source `9e9486742191d27b8571292034187c3079a9fd60`; SHA256 `69181ed60a3ed4ee7bc3d3eef68f49ad46ebf95ce60167d0bf2040953138296a` |
| Earlier installed Node fixture | Source `5dde561570db2e2b549750bd249724c6c7e8ab79`; SHA256 `76be7a3f2b3d7043c16b7c46ccaa09476c819687a4a5cfabaa9007ef4ec46bf7` |

The Node ISO was downloaded from the successful
[build run](https://github.com/btcpavao/bitcoin-core-node/actions/runs/39272912893)
and verified against its SHA256SUMS. The
[exact development artifact](https://github.com/btcpavao/bitcoin-core-node/actions/runs/39272912893/artifacts/12195999962)
contains the accepted ISO. Later commits record tests and evidence without
changing the production source used for that image. Vault integration is tracked
separately in [Vault PR #3](https://github.com/btcpavao/bitcoin-core-vault/pull/3).

## Installed acceptance results

| Boundary | Result and tested image |
|---|---|
| Native installation | Passed on the exact Node `82c2301` ISO in both BIOS and UEFI, using native Calamares and separate blank 48-GiB virtual disks. Installed boot succeeded with the ISO removed. |
| Account and startup | Both exact-image installations accepted the configured account/password, locked root, removed the live account and refused unauthenticated administrative escalation. Core remained stopped before privacy confirmation. |
| Persistent Node | Both imported public descriptors into a private-keys-disabled wallet, validated 101 regtest blocks and retained labels/UTXOs. Closing Home left the system Core service running. Real reboot changed the boot ID while preserving configuration, loaded wallet and exact chain tip. |
| Installed networking | Both exact-image installations passed the full NetworkManager/resolved sequence: clearnet IPv4/IPv6, Tor-scope direct/DNS/IPv6 blocking, stopped-Tor no-fallback behavior, genuine WireGuard handshake, glibc DNS through the tunnel, provider loss, tunnel removal and return to clearnet with wallet/chain data preserved. |
| VPN across reboot | Exact-image UEFI passed actual reboot with the provider unavailable. The restored interface, firewall and resolver prevented daemon and OS direct fallback. Restoring the isolated provider produced a genuine handshake and tunnel-only DNS; returning to clearnet preserved the chain tip. |
| Node–Vault removable media | Passed again with the exact Node `82c2301` installation and actual Vault `9e94867` OS. One detachable FAT virtual USB carried public descriptors, unsigned PSBT and signed PSBT between guests with no network devices. Each guest unmounted it before virtual detachment. |
| Native authentication | An installed desktop account invoked the production narrow snapshot action through the native polkit prompt. The resulting SQLite snapshot and checksum were verified. This used the earlier installed clone, whose application/authentication code is unchanged. |
| Public Tor transport | An earlier installed clone with corrected resolver linkage bootstrapped Tor on the public network. Core's private-broadcast path delivered the exact signed regtest transaction through an onion service to an independent Core receiver and recorded a private-peer acknowledgement. The origin ordinary mempool was empty on submission. |
| Tor across reboot | The same Tor fixture changed boot ID on actual reboot, retained Tor/private-broadcast configuration and resolver linkage, kept direct Core IPv4/IPv6 unavailable, and bootstrapped Tor again. |
| Signed maintenance | The earlier installed UEFI fixture verified and activated the genuine signed Core 31.1 baseline through the production administrator helper. It retained previous binaries and a wallet snapshot, then preserved the selected executable, loaded wallet and chain tip across real reboot. This is baseline reactivation, not certification of a different Core version. |
| Native UI and guide | Native Home, wallet dialogs, privacy layouts and the offline guide were checked at 800×600 and 1280×800. Checkbox visibility was corrected. Exact-image installer/Home screenshots and the installed polkit prompt/result are retained with the evidence. |

The complete records are in
[`validation/2026-10-19-completion/`](validation/2026-10-19-completion/).
Earlier installation, reboot and maintenance evidence remains in
[`validation/2026-10-19-installed/`](validation/2026-10-19-installed/).

### What the OS exchange verified

The installed Vault public-export implementation exported receiving/change
public descriptors from a locked signing wallet. Node compared pairing addresses
and imported a watch-only wallet. Native Core funded the Node proposal; Vault
independently decoded the intent, recipient, amount, fee and every change output.
Its pinned native Core signed in the verified RAM workspace, relocked the wallet
and exported the signed PSBT without broadcasting. Node matched the returned
proposal, rejected an incorrect confirmation hash, and broadcast only after the
exact approval. The final regtest transaction ID was
`d95125e8ce7077dfda741aaaa8b69e75df74bbb4f635ccbe7b2da92303845269`.
The signing process was stopped and the disposable RAM wallet fixture removed.

The Tor delivery check reused the earlier completed exchange transaction
`1c16ba2fb845f8748a3ce56a5b81d5a1d804d65e10c3f0d346fd657f1bb91f97`.
Only the owned clone's prior ordinary mempool was cleared before private
submission. The independent receiver returned byte-identical signed data, with
SHA256 `c768b7443e2e6750ffed205b4e7acd1b5b53e4e74411033ab1d54e9abdd43b2c`.
Core recorded one private-peer acknowledgement. This proves the tested transport
path; it does not make a general anonymity claim.

## DNS regression and source parity

The clean installed network rerun found an empty regular `/etc/resolv.conf`.
WireGuard and resolved link configuration worked, but ordinary glibc lookups
could not reach resolved. The production correction enables systemd-resolved
and a boot unit that links `/etc/resolv.conf` to its stub before NetworkManager
and the Core network policy. Image preparation and installed-target finalization
both enable the unit. Both firmware installations and the VPN reboot test passed
with the rebuilt image.

The only production differences between the earlier `5dde561` image and accepted
`82c2301` source are `prepare-image.sh`,
`runtime/etc/systemd/system/bitcoin-core-node-resolver.service` and
`runtime/usr/libexec/core-node-install-target`. Application, authentication,
network-policy, launcher and pinned Core bytes are unchanged. Public Tor and
native polkit checks used earlier installed clones with corrected resolver
linkage; signed baseline maintenance used the earlier installed UEFI fixture.
The table explicitly identifies those checks rather than treating them as reruns
on the new ISO.

## Repeated source and kernel checks

GitHub Actions runs unit/input-boundary tests, real pinned-Core integration,
native dialog checks and Linux kernel network-policy tests. These cover public
pairing, private-descriptor/wrong-network/unsafe-name rejection, PSBT identity
and explicit confirmation, encrypted public recovery round trips, wrong-password
rejection, labels/address/proposal restoration, native database recovery, unsafe
file input/output rejection, and unavailable private-route behavior. The kernel
job uses disposable namespaces, production nftables rules and real WireGuard.
Its isolated network checks complement the installed NetworkManager/resolved
results above. The production-source CI run
[`39272914426`](https://github.com/btcpavao/bitcoin-core-node/actions/runs/39272914426)
and subsequent evidence/test commit run
[`39277505555`](https://github.com/btcpavao/bitcoin-core-node/actions/runs/39277505555)
passed.

## Harness and scope notes

Test automation was corrected for native-login OCR, modifier release, unique
completion tokens, zero-glyph recognition and read-only mtools output replacement.
During the final exact-image exchange, one broadcast completion required visual
confirmation of the zero guest and unmount statuses because OCR inserted
punctuation into the unique token. The result JSON and transaction identity were
then verified, and cleanup completed. The guest acceptance passed; the record
does not claim one uninterrupted unattended controller run.

The rejected historical images and failed DNS rerun are diagnostic evidence,
not accepted candidates. The original DNS failure is retained alongside the
passing corrected results. All owned test VMs were stopped, and temporary
Desktop Commander command exceptions were restored. Physical host disks and
host networking were not changed.

The accepted maintenance scope is Core 31.1. A different Core version needs its
own version-specific acceptance. The tests do not certify arbitrary physical
hardware or a mainnet transaction. A stable publication remains a separate
release decision.
