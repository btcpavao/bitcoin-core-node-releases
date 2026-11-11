# Onboarding acceptance — 20 October 2026

This is the source-specific onboarding record. The newer interface ISO, current
download and manual launcher are documented in [UI acceptance](UI-VALIDATION.md).

The revised installer, automatic login, default Core startup and optional password workflow passed the recorded development acceptance. The artifact remains on the development branch and draft PR.

## Artifact identity

[Download the development ISO artifact](https://github.com/btcpavao/bitcoin-core-node/actions/runs/39403910195/artifacts/12256649715).

| Item | Identity |
|---|---|
| Final image source | `f8e546a3c450acd20caa11c63833cac7d21ef9f0` |
| Final ISO SHA256 | `b4fa127133e21d3bc4aea5c29ce11b803a06b8cc6ed15c4e67c3fcaefcd6f09c` |
| Password lifecycle image source | `8a5d2c5c4a04ff8001f984c34a3e12f5c03abeab` |
| Password lifecycle ISO SHA256 | `907ef1377ae5e319f84f46c11d7851e8393da3c9e207f120db5ea1d224e98be1` |
| Pinned Bitcoin Core | Upstream 31.1; executable SHA256 `986e63b3c8770f08d0059820ad3dd085d1ab9e1bea23946c243f858a06888a08` |

The final source differs from the password lifecycle source only in `GUIDE.html` and `GUIDE.txt`. All executable, account, LightDM, polkit and default configuration source is identical. The subsequent onboarding evidence commit retained tests/evidence and a manual VM launcher without changing that image payload. The later interface revision has its own image and acceptance record.

## Delivered behavior

Calamares installs the whole system without a username/password form. The fixed installed account is `node`, with a locked password and automatic local LightDM login. Core 31.1 is already included. Fresh installed systems initialize matching mainnet clearnet/archive settings and start Core without a Network & Privacy confirmation. Missing or corrupt configuration on an existing installation still fails closed.

Home now shows the Bitcoin logo above the title, the Debian logo beside the footer, and the clearer live-session action **Install system to disk**. **Login & Password** can enable a password later. Password login uses username `node`; disabling it requires the current password and restores automatic login.

The user explicitly authorized the narrow ISO-only policy: in automatic-login mode, only the active local `node` session receives password-free access to the two fixed Node administration/login actions. Once a password is enabled, both require fresh self-authentication. There is no generic passwordless sudo. New passwords use stdin; disabling login locks the existing hash instead of creating an empty password. Host accounts and screenshot software were not changed.

## Recorded acceptance

| Check | Result and exact scope |
|---|---|
| Final native installation | PASS, BIOS and UEFI, separate blank 48-GiB virtual disks, native Calamares without Users page. ISO removed for installed boot. |
| Final default startup | PASS on both: automatic desktop login, matching default configuration, running mainnet Core, no mandatory profile confirmation, no live user and no passwordless sudo. |
| Final local administration | PASS on both: active local session authorizes bounded setup and wallet snapshot; snapshot is SQLite with matching checksum. |
| Final actual reboot | PASS on both: changed boot ID, automatic login, running service, watch-only wallet, labels and 101-block regtest tip persist. The initial fixture also verifies public UTXOs. |
| Optional password enablement | PASS on `8a5d2c5` UEFI through the real Login & Password dialog. Noninteractive checks deny both fixed administration/login actions afterward. |
| Password authentication | PASS on that same installation: native polkit prompt permits explicit Core restart with the fixture password; an actual reboot requires graphical login as `node`. |
| Return to automatic login | PASS on that same installation: existing-password authentication is required; a second actual reboot automatically logs in and retains wallet/chain state. |
| Native layout | PASS at 800×600 and 1280×800. Home and password dialog inspected; final installed Home confirms both logos and running Core. |
| Source/build regression | PASS: 12 local tests, Python compilation, shell syntax and diff checks; final source push/PR checks and source/Core/kernel/image workflow all green. |

All transaction fixtures were public-only watch wallets on regtest. Acceptance VMs had no NIC; mainnet startup was checked locally before switching the owned fixture to regtest. These checks establish startup and persistence, not a full mainnet download.

The earlier [19 October acceptance](VALIDATION.md) separately records complete VPN/DNS/failure/reboot, Tor delivery/reboot, Node–Vault signing exchange and signed Core 31.1 baseline maintenance. Those complete scenarios were not repeated for this onboarding revision; the source/Core/kernel regression checks were repeated. A different future Core version still requires its own acceptance.

## Evidence and execution notes

[JSON records and native screenshots](validation/2026-10-20-onboarding/README.md) retain the tested firmware/image identities and actual boot IDs. All four owned onboarding VMs were shut down normally.

The first `8a5d2c5` BIOS controller queried QMP before its socket was ready. The running guest was resumed and passed; the controller now retries initial QMP readiness. Both final-image runs completed automatically. The final build's first kernel-dependency attempt hit an unrelated runner Microsoft package repository 403; rerunning failed jobs succeeded.

## Manual VM test on the development machine

The manual launcher now selects the newer verified interface ISO documented in
[UI acceptance](UI-VALIDATION.md). Run:

```bash
~/bitcoin-core-node-resume/tools/test-node-vm.sh
```

The launcher verifies SHA256SUMS and opens QEMU with a separate 48-GiB virtual disk, 3 GiB RAM and NAT networking. The same virtual disk is reused on subsequent runs. Install with **Install system to disk**; after installation it boots from that disk. Default login is automatic. If a password is enabled later, the username is `node`.
