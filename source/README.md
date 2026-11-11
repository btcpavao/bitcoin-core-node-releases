# Bitcoin Core Node — development

The installer and desktop now reuse Bitcoin Core Vault's actual Calamares,
Home widgets, taskbar and window-manager configuration. Node retains its
networking and persistent storage. See [the source provenance](installer/README.md)
and [the current verification record](docs/VAULT-UI-VALIDATION.md).

Persistent Debian 13 amd64 environment built around verified upstream Bitcoin
Core 32.1. The separate offline Vault holds signing keys; this online system is
intended to watch the blockchain, prepare PSBTs and broadcast signed transactions.

Core 32.1 local acceptance is recorded in docs/CORE-32.1.md. Earlier reports
remain evidence for their original images only. This is a local development build.

## Source layout

- `app/`: local cookie RPC, persistent configuration, privacy policy and Qt Home.
- `runtime/`: systemd services, narrow polkit administration and Calamares setup.
- `build-iso.sh`: disposable Debian live-build entry point with pinned Core hash.
- `tests/`: automated input/boundary tests; these do not replace OS acceptance.

Run `python3 -m unittest discover -s tests -v` for source-level tests.
Build only in an owned disposable Debian 13 environment as root with
`NODE_DISPOSABLE_BUILDER=1 ./build-iso.sh`. Never run the build hooks on a normal
installed host. Build output is a development artifact, not a stable release.

## Current foundation

The unmodified native Bitcoin Core GUI runs under its own non-root service
account. Core starts when the user opens **Bitcoin Core**; its native first-run
window controls pruning. Closing Core stops it normally, and rebooting returns
to Home with Core stopped. Fresh installations initialize clearnet networking.
Startup requires an installed marker, a valid stored profile, matching per-boot
firewall attestation, persistent storage and exact verified Core GUI bytes.

Core P2P Tor privacy and whole-device VPN privacy have distinct scopes.
WireGuard import rejects scripts, split tunnels and hostname endpoints. Imported
private tunnel keys are stored only in root-owned mode-0600 configuration.
Installed profile, installer and kernel networking checks have passed within the
[documented acceptance scope](docs/VALIDATION.md).

Local members of `bitcoin-rpc` can access Core RPC directly. Application-level
watch-only restrictions cannot stop an administrator or an authorized RPC user
from bypassing the custom workflow. No claim of protection against a compromised
administrator or compromised kernel is made.

## Hardware support

See [hardware support and remaining limitations](docs/HARDWARE-SUPPORT.md)
for the Debian firmware coverage audit, Broadcom/macOS caveats, and
physical-device acceptance matrix. A package-inclusion test does not establish
that a particular laptop or wireless adapter works.

## Provenance

Upstream archive: `bitcoin-32.1-x86_64-linux-gnu.tar.gz`.
SHA256: `61545c17c3120fb7412f896d248b11993af04ec8817aad3649c55b2afb044963`.
The upstream archive checksum and eight release signatures were checked using
the existing development keyring during Vault integration. Tested daemon SHA256:
`580ac61190154da31aac3f82d13c4254ef453d70e1bf2c39d338dac5129c92ac`.
Builds reject a differing archive. No upstream cryptography, wallet, consensus,
validation or transaction code is modified.

Vault integration: https://github.com/btcpavao/bitcoin-core-vault/pull/3

## Native public wallet and transaction workflows

Vault: **Bitcoin Core → File → Export watch-only wallet**. Node:
**Files → Public Wallet Transfer**, then **Bitcoin Core → File → Restore Wallet**.
Only transfer the public export, never the original signing wallet database.
Core performs all wallet export/restore operations. Obsolete custom descriptor
JSON import/export and recovery-package creation are removed.

Watch-Only Wallets manages loaded public descriptor wallets; Core owns PSBT creation/loading/broadcast and wallet backup/restore. The custom Create Transaction, Import Signed PSBT and Wallet Backup tools and their privileged snapshot action are removed.

## Private Workspace and GPG files

Home provides Private Workspace, Encrypt Files and Decrypt Files. Private Workspace is a bounded tmpfs with noswap, nodev, nosuid and noexec. Swap, hibernation and disk crash dumps are disabled. Files and decrypted output disappear after restart or shutdown. Core blockchain/wallet data, ordinary home files and Public Wallet Transfer remain persistent. Restoring a wallet into Core creates a persistent copy.

Node's GPG file tools now use Vault's reviewed AES-256 CFB+MDC profile, with
independent nested layers and portable layer filenames. A single verified
Bitcoin Core SQLite wallet.dat encrypts directly, without TAR; other
individual files, directories and sets are packaged as standard TAR.
The built-in recovery also accepts older AES-256 OCB/TAR backups and
ordinary authenticated single-layer GPG files in explicit mode.
Every encrypted layer and full recovery are checked before publication.
Decryption authenticates before publishing into RAM. Passphrases travel through an anonymous pipe, not argv or logs. No existing destination is overwritten. For an active wallet, first use Core's File → Backup Wallet to save a consistent database in Private Workspace, then encrypt that file.

See the in-image Guide and docs/PRIVATE-WORKSPACE.md for storage boundaries and acceptance. Historical reports retain their original image scope.

## Controlled maintenance

Settings → Software Updates checks official upstream release information only on request.
Core 32 maintenance archives must match signed checksums and at least two distinct,
currently valid bundled release signers. The bundled public key bytes are pinned;
the baseline signature material and verification record live in `provenance/32.1`.
Expired keys are excluded from the acceptance threshold. Major-version changes
and downgrades require separate project review and are refused by this mechanism.

After explicit review and local authentication, maintenance checks free space,
stops Core cleanly, preserves wallet databases/settings and activates a separate
verified binary directory. The launcher checks the selected GUI hash on every
start. No automatic wallet rollback or network-policy change is performed.
Real signed-archive verification and rejection tests pass. Installed baseline
reactivation, wallet snapshot retention and reboot persistence also pass; this
does not certify upgrades to untested future versions.

## KeePassXC and system time

Home includes Vault’s native six-word KeePassXC generator with a verified RAM-only profile. The system clock is always visible and opens the same Date & Time controls as Settings. See [scope and validation](docs/KEEPASS-CLOCK.md).

Settings offers verified offline blockchain backup/import; see docs/CHAIN-BACKUP.md. Home shows status and date/time above Network, Restart and Shutdown at the bottom right.


## Mandatory installer ownership acceptance

The Node image must preserve 32 non-root UID/GID/mode entries from the verified
Debian 13 Node baseline, including system D-Bus activation, Tor, Bitcoin Core
storage and protected system files. `tests/check_ownership.py --iso FILE.iso`
is a mandatory post-build gate, not a substitute for physical SATA installation
or boot/reboot testing. Wrong ownership can silently hide all installation
drives from Calamares, even when lsblk sees the disk.


## Settings features — 2026-11-03

- **Mouse speed:** XInput/libinput per-device slider for Bluetooth and USB mice,
  with an unprivileged hotplug watcher persisting preferences across restarts.
  The official Debian `xinput` package is included in fresh builds.
- **Software Updates:** explicit package list, review before installation,
  real APT download/configuration stage progress and reboot warnings.
  Debian/KeePassXC maintenance no longer deliberately stops Bitcoin Core;
  the separate signed Core upgrade retains its existing graceful stop process.
  Distribution package scripts may still briefly restart other OS services.
- **Connectivity:** a red/offline or green/online dot with explanatory labels
  based on actual Bitcoin peer connectivity, not simply Wi-Fi signal.
- **Desktop stability:** modal dialogs are never hidden by background clicks;
  geometry updates are coalesced into parent-owned timers. The stopped-state
  GUI must remain responsive after Bitcoin Core is closed.

These features require physical T550 validation, including Bluetooth mouse
adjustment, a real Debian update and the stopped-Core GUI transition.

## iPhone hotspot / Wi-Fi reconnect robustness (2026-11-03)

A selected iPhone hotspot can change access-point BSSID or frequency when its
display sleeps or wakes. The helper now retries using only the originally
selected exact UTF-8 SSID and rejects insecure protocol downgrades; its
NetworkManager activation reports a fixed, secret-free diagnostic class
for unavailable adapter/network, unsupported WPA3 security, authentication,
authorization or timeout. The GUI provides an iPhone Maximize Compatibility
hint and keeps the native advanced settings fallback. The Wi-Fi passphrase is
still passed in a private process pipe, never command arguments or logs.
A physical T550 hotspot test remains required.

Earlier test builds displayed a build marker in Node Settings. The new streamlined Settings removes this label; the exact build is still recorded in the ISO metadata and release manifest.
\nLatest indicator copy: Bitcoin Core is online / Bitcoin Core is offline, with a vivid green #1CF46B or vivid red #FF5151 solid dot; no abbreviated “Node” copy even in compact display mode.\n

## Home blockchain progress, disk usage and status controls (2026-11-03)

- Replaces the animated sync spinner with **100 discrete segments**, filled
  solely from Bitcoin Core's `getblockchaininfo.verificationprogress`.
  Header pre-sync and waiting-for-peers messages remain accurate even at 0%.
- Beneath the sync meter, one filesystem-usage bar shows the **percentage
  free and free GiB** on the verified blockchain data mount, accounting for all
  files on that disk. It does not separate blocks and chainstate. If an
  external selected SSD cannot be verified, the indicator is hidden rather
  than incorrectly displaying root filesystem capacity.
- Clicking the bottom-left Bitcoin Core status opens an action dialog:
  **Start Bitcoin Core**, **Pause/Resume sync** (Core RPC `setnetworkactive`),
  **Stop Bitcoin Core**, **Restart Bitcoin Core**. Stop and Restart require
  explicit confirmation. All controls operate asynchronously and never
  power off the Debian computer. Pause disconnects peers while Core and its
  wallet/background processing remain loaded; it is not process suspension.
- Core service controls are now accessed from the bottom-right Bitcoin Core status indicator. The separate Start/Stop/Restart controls are removed from Settings.

Physical T550 verification is still required; test these controls with
disposable wallets first.


## Right-hand status/time/control stack (2026-11-03)

The online/offline Bitcoin Core status indicator (red/bright green dot and
the complete "Bitcoin Core is offline/online" label), the date/time button,
and the three Network / Restart / Shutdown buttons are stacked vertically
in that exact order at the bottom-right of Home. All remain independently
clickable. The left footer is empty, while "Powered by Debian GNU/Linux"
remains exactly centered. The layout is verified in headless Qt at 800x600,
1024x768, 1366x768 and 1920x1080, including active sync, the stopped Core
state and optional watch-only wallet cards, without clipping or scroll.
The bundled Power and Network icon artwork has lossless transparent PNG
equivalents so icons remain visible even without an installed Qt SVG loader.


## USB / External Drive destination selector for Chain State backups (2026-11-03)

The previous Qt `Choose folder` picker started in `/media` without a proper
sidebar for USB drives that Thunar/GVfs had already detected. The safe
`USB / External Drive…` dialog now discovers USB-backed partitions through
lsblk, including external SSDs (which may have RM=0) and USB sticks.
The device can be mounted by the local desktop user with UDisks2 and Polkit,
without formatting; a selected mount root or its existing subfolder becomes
the destination. Ordinary `Choose folder` also provides explicit sidebar
shortcuts to mounted USB filesystems.

The privileged backup/import backend now permits verified nonvolatile USB
mounts under `/run/media/node/<disk>` as well as `/media/node/<disk>`.
Unrelated `/run` locations and RAM workspaces remain forbidden. Destination
access and filesystem checks occur **before** Bitcoin Core is stopped; an
absent USB must not interrupt synchronization. The existing file inventory,
space checks, FAT32 limits, streamed SHA-256 verification, cancellation and
durable final rename remain intact. Read-only USB can be an import source,
but backups require writable storage.

Automated tests include virtual device discovery, asynchronous unmounted
USB → UDisks2 mount → selection, Qt UI controls, a full synthetic
blocks/index/chainstate copy with verified manifest and preflight failure
without stopping Core. Live USB verification on ThinkPad T550 is pending.


## Final T550 right-footer alignment fix (2026-11-03)

- The T550 reported that the clock's last minute digit (for example
  `16:30`) was clipped: the fixed QPushButton width accounted for text
  but not icon, icon-text spacing and native Qt style padding.
  The footer now computes a safe width from the real Qt button size hint,
  font metrics and icon dimensions, with a minimum of 218 pixels.
  The symmetrical footer zones grow together if DPI requires more width.
- Bitcoin Core peer status and the clickable date/time button are centered
  over the Network / Restart / Shutdown group. The three original power
  controls are centered as a single row and retain their existing icons,
  accessibility descriptions and graceful shutdown behavior.
- `Powered by Debian GNU/Linux` remains exactly centered horizontally;
  its logo/caption now form a compact group aligned near the lower row
  rather than distributing vertically through the full 112-pixel footer.
- Desktop and clock Qt regressions cover 800x600, 1024x768, 1280x720,
  1366x768, 1920x1080, 125%/150% scaling and minute changes at 16:30,
  16:39, 23:59 and 00:00. The Core service, GPG, USB Chain State
  destination chooser and all other functionality are unchanged.

Physical T550 layout acceptance is still required before public release.


## Footer button icon parity with Vault (2026-11-03)

The blue Restart and red Shutdown buttons now have full-color renders
of the original elementary-Xfce SVG assets used in Vault. Network displays
a visible white symbol on a vivid green circle. Earlier PNGs lost their
colored fill and network glyph during ImageMagick conversion; the new
192×192 transparent PNGs are rendered via librsvg. Footer alignment,
clock, actions, blockchain data and services remain unchanged.
See docs/ICON-RENDERING-20261103.md.


## Settings cards and navigation (2026-11-04)

The Home tile is now **Settings** (formerly Node Settings). Settings contains
ten equal-sized, full-icon tiles in two rows: Bitcoin Core Network & Privacy,
Login Password, Software Updates, Date & Time, Backup Chain State,
Import Chain State, Network Connections, Bluetooth Devices, Mouse Speed,
and Bitcoin Core Status. Network Connections retains the old Network &
Privacy icon, both Bitcoin Core cards display the Bitcoin logo, and Bluetooth
uses the existing elementary-Xfce device artwork. Only a small **Exit**
button remains in the lower-right.

Removed from Settings: build/test version label and duplicate Bitcoin Core
Start/Stop/Restart control row. The existing Bitcoin Core management
functions remain available through the bottom-right Core status indicator.
The Bitcoin Core Status tile opens the unchanged detailed RPC/chain/peer
report with **Go Back** (return to Settings) and **Close Settings** (return
to Home). No Core process or blockchain data is changed by opening/closing
the dialogs.

The bundled Bluetooth icon comes from Debian's elementary-Xfce icon theme,
whose copyright and licensing are already included in this distribution.
Physical T550 acceptance remains pending.


## Settings, Core status navigation, restart button and wallet deletion (2026-11-04)

- **Settings** replaces the Node Settings Home card. Ten equal full-size tiles
  show Bitcoin Core Network & Privacy, Login Password, Software Updates,
  Date & Time, Backup Chain State, Import Chain State, Network Connections,
  Bluetooth Devices, Mouse Speed, and Bitcoin Core Status. Bitcoin Core cards
  have the Bitcoin logo; Network Connections carries the former privacy icon,
  while Bluetooth has its native Debian device icon. The test-build label and
  duplicate Core Start/Stop/Restart row are removed. A compact Exit button
  closes Settings.
- Bitcoin Core Status retains its existing Blocks, Headers, chain, peer and
  validation data. **Go Back** reopens Settings, while **Close Settings**
  returns to Home. The bottom-right Core status indicator retains its
  Start/Pause/Stop/Restart controls.
- Restart/Shutdown confirmation now uses explicitly sized buttons with a
  wider **Cancel** label and native style; no change to graceful Core flush,
  countdown or user authorization.
- The Thunar right-click menu offers **Permanently Delete Bitcoin Core Wallets…**
  for one or multiple selected named wallet folders inside the read-only
  Core → wallets view. The entire Core view remains read-only.
  The explicit red **Permanently Delete** confirmation uses Vault's dialog
  styling and displays every selected wallet; no typed name is required.
  The privileged helper accepts only ordinary, unloaded wallet directories,
  refuses the whole batch if any selected item is invalid or loaded, and
  never accepts the wallets root, blockchain, chainstate or arbitrary paths.
  It stops Core once, overwrites each selected wallet file three random passes
  and one zero pass, then removes that wallet's directory. It restarts Core
  only after the whole batch succeeds when it was running beforehand.
  The progress dialog automatically closes after verified success and unlocks
  a normal **Close** button after failure.
- **SSD/data-erasure limitation:** multiple overwrite passes DO NOT guarantee
  secure erasure on SSDs, journaling/CoW filesystems, previous backups or
  snapshots. Treat this as best-effort deletion. Verify separate wallet
  backups first; removing the sole copy of a private-key wallet can destroy
  access to funds. Wiping is not reversible.

The user-facing Home, networking, blockchain and wallet backup workflows
are otherwise unchanged. Verify the exact ISO physically on T550 before
public release.


### Optional login password

Installed systems sign in automatically by default. Settings → Login Password
can set, change, or remove a password without reinstalling. Changes take effect
at the next login; they do not close the current desktop session. An existing
password must be authenticated before it can be changed or removed.

There is no Node minimum-length or character-complexity rule. Spaces and Unicode
are preserved exactly. Debian's libxcrypt input boundary is 511 UTF-8 bytes;
longer text is rejected without changing credentials, never truncated. NUL and
line breaks cannot be passed through chpasswd's single-line account protocol.

A login password does not encrypt storage. Previously encrypted installations
continue to require their separate disk-unlock password. Core start/stop/restart
and computer restart/shutdown use separate helpers restricted to those exact
operations and to the active local Node session. Package installation, privacy
changes and other administration keep their existing authorization rules.

## Backup and Restore

See [the grouped backup workflow](docs/BACKUP-AND-RESTORE.md) for blockchain, encrypted watch-only wallets, portable Core and Node configuration, including restore limits and minimized-window recovery.

## Backup UX revision

See [Backup navigation, optional encryption and RAM PSBT exchange](docs/BACKUP-UX-20261106.md) for the current transfer behavior and acceptance scope.

## Guide, USB and software-update checks

See [8 November desktop/update changes](docs/GUIDE-USB-UPDATES-20261108.md)
for the independent technical-details window, illustrated configuration recovery,
USB file selectors and the verified official KeePassXC metadata fallback.
