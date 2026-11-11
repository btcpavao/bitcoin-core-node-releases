# Backup and Restore

Settings now has one **Backup and Restore** card. The grouped dialog offers
Backup and Restore for four separate categories. Returning from a child returns
to this group, then Back to Settings returns to the same Settings window.

| Category | What it transfers | Activation |
| --- | --- | --- |
| Blockchain | Existing complete retained blocks, index, xor data and chainstate | Existing verified chain-copy/import workflow |
| Watch-only wallets | Native Core public-only exports with public descriptors, address book, labels and transactions | Core restorewallet, with Core running |
| Bitcoin Core configuration | Supported numeric and native GUI preferences only | Reviewed, on next restart |
| Node configuration | Saved Wi-Fi/Ethernet credentials, managed WireGuard/privacy, time zone/NTP, keyboard, display scale, matching mouse preferences, plus portable Core preferences | Reviewed, on next restart before networking |

Configuration and watch-only backups offer **Encrypt backup (optional)**, off
by default. Plain `.json` files have a bounded envelope and content checksum;
anyone with the file can read its contents. Node configuration can include Wi-Fi
passwords and VPN keys, and public wallet data is privacy-sensitive. A checksum
is not proof of source authenticity. Keep plain backups private.

Optional `.gpg` exports use authenticated AES-256, actual decrypt verification
and USB read-back. Any nonempty passphrase, including `1`, is accepted; there is
no minimum-strength rule. Strong random passphrases are recommended. Existing
GPG backups remain readable. Transient staging stays in verified private RAM;
passphrases do not enter argv, environment variables or logs. No private signing
key is included by the watch-only workflow.

See [the UX revision](BACKUP-UX-20261106.md) for independent windows, concurrent
configuration exports, manual Core restart after chain backup and RAM-only PSBT
exchange. Back or minimize during an operation does not cancel it.

## Watch-only wallets

The helper uses Bitcoin Core 32.1's native `exportwatchonlywallet` API only after
`getwalletinfo` confirms private keys disabled, descriptor wallets enabled and no
external signer. It never reads a source wallet database or invokes `backupwallet`
for this collection. A previously unloaded wallet can be temporarily loaded to
check its type; it is unloaded again afterwards. Signing wallets are counted as
skipped, not exported. Unsupported names/types are likewise not silently claimed
backed up. The result explicitly lists included names and the skipped count.

The public-only exports are independently opened by pinned upstream Core in a
private network namespace and copied RAM datadir before publication or import.
The receiver restores through native `restorewallet`, never by overwriting a
wallet directory. Existing names get a generated alternative name. A root-only
receipt allows retrying the same backup without duplicating completed
wallets. This is **per-wallet resumable restoration**, not an all-or-nothing
transaction across the entire collection: completed wallets remain if a later
one fails. Native operations can need a rescan and are not interrupted mid-call.
The UI marks that stage noncancellable and shutdown/sleep is inhibited.

Both nodes need the same Core version/network. The initial transfer limits are
32 wallets, 32 MiB per native export and 64 MiB combined before JSON encoding,
subject to available private RAM. Larger collections fail with no partial
published backup. Core must already be running. Restored wallets may need block
history unavailable on a pruned node; blockchain import does not recreate blocks
which were already pruned. Core's watch-only export cannot derive previously
uncached hardened keys; the original signing wallet remains the authority.

## Configuration boundaries

See [portable settings](SETTINGS-SNAPSHOT.md) for the exact portable set and
rollback model. Core-only backups do not collect Wi-Fi/VPN secrets. Whole-Node
configuration includes the supported Core preferences, so a separate Core backup
is optional. Explicitly staging both applies whole-Node configuration first and
then the Core-only preference set.

This is not a raw OS clone. Login/password hashes, disk encryption, machine ID,
source disk paths/UUIDs, Bluetooth pairing and arbitrary scripts are not cloned.
The preview reports unsupported custom Core options, missing stored Wi-Fi
passwords and unsupported certificate/third-party VPN profiles. WireGuard is the
Node's managed, strictly validated single-peer profile; use a new VPN peer/static
IP if both old and new computers will operate simultaneously.

## Minimize and return

The X11 taskbar now retains normal and iconified Home-owned dialogs even when Qt
sets `SKIP_TASKBAR`. Settings, the backup group and progress dialogs remain tasks
while Core is closed for a chain copy. Selecting a parent restores its minimized
parents and deepest active modal child; **Restore** is also available in the
context menu. The panel hides only when no task remains. Minimization neither
cancels the copy nor changes the privileged operation.

## Verification scope

Local suites cover schemas, encrypted GPG round trips, native libnm profile
normalization, rollback and power-loss recovery, menu navigation and actual
Openbox/X11 minimized-modal restoration. Disposable installed VMs exercise
synthetic Wi-Fi/Ethernet/WireGuard transfers, real cold-boot application, separate
Core configuration import and native Core watch-only export/restore with name
conflicts and repeat import. Real network association, VPN handshake and full-size
physical wallets/chains still require acceptance on the user's actual hardware.
