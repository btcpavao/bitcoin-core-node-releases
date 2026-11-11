# Vault-derived Node interface — 21 October 2026

**Status: the final rebuilt ISO is now verified through native UEFI and BIOS installation and installed boot, with UEFI Home Restart/Core data persistence and native shutdown tested. This remains a development candidate, not a stable release.**

[Exact 21 October evidence and screenshots](validation/2026-10-21-final/README.md).
[Successful GitHub Actions ISO build](https://github.com/btcpavao/bitcoin-core-node/actions/runs/39583320193).

## Implementation and reference

Vault reference: `110f8ccd651408145de6ec4acd6a1ad70b84309c` from
`btcpavao/bitcoin-core-offline`. [Provenance](../installer/VAULT-ORIGIN.json)
records the carried-over Calamares source patches, branding, Home components,
taskbar, Num Lock helper and Openbox configuration.

Node uses Vault's actual Keyboard → Disk → Review installer and finish screen.
Its installed session retains networking and persistent storage. The installer
session has a retry/diagnostic path instead of leaving an empty live desktop.
The native upstream Core GUI opens manually and owns its initial pruning choice.

## First image: installer and UI pass, shutdown persistence fails

Source: `771511332ab27296a5f65c039497b8b93595b1dc`.
[Build 39428225055](https://github.com/btcpavao/bitcoin-core-node/actions/runs/39428225055)
passed source/Core, isolated kernel networking and image jobs.

Downloaded ISO SHA256:
`6f90295de60e414d3136dc0c12c1a0bcce469e60780a906e8a0cf5606da70b5c`.

The pinned custom Calamares package and corresponding modified source are in the
same artifact. Package SHA256:
`b3e9ee8504bc5ae96c6cd4720e102e01741f33c76032bfdf14b40e4efb5ef56f`.

An owned UEFI QEMU VM, 48-GiB disk, 2 GiB RAM and no NIC verified:

- Actual native installation and **Restart into Bitcoin Core Node** reaching
  installed Home, without QMP stop/relaunch.
- Vault layout, logos/footer, application cards, taskbar and power icons.
- Num Lock on; middle click closes Terminal; Core initially inactive.
- Native Core Intro/pruning, verified upstream bitcoin-qt as bitcoinnode and
  pruning active over local RPC.
- GPG checkbox initially off and a green check after selection.

The first Home restart failed the chain-tip retention gate: the recent 101-block
regtest chain returned at height zero. The persistent Core log records an X11
connection failure; the system journal records Core exiting with SIGABRT while
the desktop session/LightDM were stopping. Wallet data remained, but this image
is not acceptable for use. The failure and screenshots are retained in
[the evidence directory](validation/2026-10-20-vault-ui/README.md).

## Shutdown correction and local verification

Implementation commit: `8e554a8343d4c617452159cc25f06ffae790c3ab`.

Home power actions now use the bounded administration helper, which waits for
Core to stop successfully before requesting restart or power-off. On GUI start,
the helper resolves the fixed node account's active local X11 session from
logind, validates its identity and binds/orders Core before that session closes.
The service also stops before the display manager.

The four changed runtime files were applied to an offline copy of the installed
VM disk. This is explicitly a patched VM test, not a rebuilt ISO.

Passed on that copy:

- Native Core startup and the actual systemd session ordering/binding.
- Actual Home Restart with Core running.
- A changed boot ID, the exact same 101-block tip, public-only wallet and address
  label after manually reopening Core.
- Actual Home Shut down with Core running; the owned QEMU process exited
  without QMP quit.
- 35 local unit/boundary tests, Python compilation and diff checks.

The test tip was
`17a96d7d6ed7212d3dead1f7be9825e05d91c7d0408f261c3382571aa096ee2f`.
Both before/after JSON reports are retained.

## Exact rebuilt ISO acceptance — 21 October 2026

The existing development branch was pushed, and GitHub Actions run
[39583320193](https://github.com/btcpavao/bitcoin-core-node/actions/runs/39583320193)
completed **source/Core**, **kernel-network**, and **development-image**
successfully for source `49df04789d7a109c9e99b2fcda9986b119f08f1a`.
Downloaded ISO SHA256:
`61e67143f6da9fad9d08bffc8796fb8366cbb8c12d040a13475cb8ef02eb63ef`.

On the exact, **unmodified** ISO, new owned offline 48-GiB UEFI QEMU:

- Native Vault-derived installer from Keyboard through disk review, final
  confirmation, and **Restart into Bitcoin Core Node** reached installed Home.
- Installed GUI/taskbar and Num Lock passed, Core remained stopped until the user
  explicitly launched the native upstream Bitcoin Core 31.1 GUI and enabled pruning.
- Running `bitcoin-qt`, configured regtest and loaded public-only wallet passed the
  actual installed GUI/process/local-RPC checks.
- With Core active, native Home **Restart** was used, not QMP or guest service
  shortcuts. After the new desktop session Core was initially stopped. Opening
  native Core again retained **202 blocks**, the exact chain tip, the watch-only
  wallet and the labeled receiving address. The boot ID changed.
- With Core running again, native Home **Shut down** cleanly stopped the guest
  and exited the owned QEMU process **without QMP quit**.
- All 35 local unit tests and syntax/diff checks passed before the ISO build.

A second separate **BIOS** 48-GiB offline QEMU passed native installation,
the finish-button installed boot, actual installed GUI/taskbar/Num Lock checks
and native Home **Shut down** without QMP quit. Its Core/regtest persistence
lifecycle was not repeated; that deeper check is UEFI-specific.

The full original evidence, guest JSON results and screenshots are retained in
[21 October UEFI and BIOS acceptance](validation/2026-10-21-final/README.md).

This acceptance does **not** claim full mainnet synchronization, hardware
installation or repeated full VPN/Tor/PSBT end-to-end on this exact source.
Prior results keep their original source scope. The development artifact
also carries its own status warning; do not label this a stable release.
