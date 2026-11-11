# Historical Node interface acceptance — 20 October 2026

This record applies only to source `2345d61`. The current revision is documented
in [Vault-derived UI acceptance](VAULT-UI-VALIDATION.md).

The requested launcher, installer branding, dropdown and power-button changes
passed native UEFI installation and actual GUI restart/shutdown acceptance.
This remains a development artifact on the existing draft PR.

## Image identity

[Download the current development artifact](https://github.com/btcpavao/bitcoin-core-node/actions/runs/39411308099/artifacts/12260540776).

| Item | Identity |
|---|---|
| Image source | `2345d61736b7449474c61bdae26f46763c61fcbd` |
| ISO SHA256 | `bba419c93159795f4ffe210861bcdae65c8462bff3ad638c7907b02e24bba376` |
| Workflow | `39411308099`, source/Core, kernel networking and image jobs passed |
| Bitcoin Core | Verified upstream 31.1, unchanged |
| Manual image directory | `/home/pavao/node-v1-validation/2345d61` |

The image checksum was verified after download. Later evidence, documentation,
VM-controller and manual-launcher changes do not alter the image payload.

## Delivered behavior

- Calamares displays the Bitcoin logo above the Node title and the Debian logo
  with **Powered by Debian** at the bottom.
- Home uses icon cards with native application icons and the Vault visual style.
  **Node Settings** groups **Network & Privacy**, **Login & Password** and
  **System Updates**, with separate Bitcoin Core service controls.
- The Archive/Pruned popup uses the dark palette without the former white bands.
- Home includes the same blue Restart and red Shut down SVG buttons as Vault.
  Their original license and attribution are retained. Each uses an ordinary
  confirmation with Cancel as the default; there is no RAM-loss warning or
  countdown. Confirming invokes the normal systemd reboot/poweroff path, which
  stops Core through its existing service configuration.

Network enforcement, wallet/transaction logic and the previously authorized
bounded authentication policy are unchanged.

## Recorded checks

| Check | Result and scope |
|---|---|
| Native installation | PASS on this exact ISO with UEFI, blank 48-GiB virtual disk, no Users form and ISO removed for installed boot |
| Installed startup | PASS: automatic local login, running mainnet Core, expected defaults, no mandatory setup prompt and no generic passwordless sudo |
| Branding and navigation | PASS on the native installed/live UI: actual icons, footer, Node Settings and Archive/Pruned popup inspected |
| Restart button | PASS through the actual Home footer button and confirmation; boot ID changed and automatic login returned |
| Persistence | PASS after that restart: Core running, same 101-block regtest tip, loaded watch-only wallet and receiving-address label retained |
| Shutdown button | PASS through the actual Home footer button and confirmation; owned QEMU process exited normally without a QMP quit |
| Native routing/cancellation | PASS locally with system calls mocked: seven settings routes, both power confirmations, both cancellations and invalid-action rejection |
| Small-screen layout | PASS native Qt at 800×600 and 1280×800, including Home and Node Settings |
| Regression/build | PASS: 12 local tests, compilation, shell syntax, source/Core and kernel-network CI, successful image workflow and source push/PR CI |

The VM had no NIC. Mainnet startup was checked locally before switching this
owned public-wallet fixture to regtest; this is not a full mainnet synchronization
test. The before phase also verified a consistent public-wallet SQLite snapshot.
The final normal shutdown left this acceptance VM stopped.

[Retained screenshots and JSON evidence](validation/2026-10-20-ui/README.md).

This exact UI image was tested with UEFI. Earlier BIOS/UEFI installation and the
optional password lifecycle retain their exact source scope in the
[onboarding record](ONBOARDING-VALIDATION.md). The
[19 October record](VALIDATION.md) separately covers full VPN/Tor, Node–Vault
exchange and signed Core 31.1 maintenance. Those complete scenarios were not
repeated for this interface revision; their backend code is unchanged.

## Manual VM test

Close the previous manual VM, then run:

```bash
~/bitcoin-core-node-resume/tools/test-node-vm.sh
```

The launcher verifies SHA256SUMS and uses a new separate
`~/node-vm-manual-2345d61/node.qcow2` disk, 3 GiB RAM and NAT networking.
The same new disk is reused on later runs; the earlier test disk is preserved.
Select **Install system to disk**. Installed login is automatic. Optional password
settings are under **Node Settings → Login & Password**; the username is `node`.
