# Portable Node settings backup and restore

## User flow

Settings → **Backup and Restore → Node configuration** opens the settings workflow.
The separate **Bitcoin Core configuration** row transfers supported Core preferences only.
Choose a persistent folder or mounted USB and save. Encryption is optional and
starts off: a plain `.json` export is readable by anyone who has the file, and
may contain network credentials. Its checksum detects corruption, not forgery.

To encrypt, select **Encrypt backup (optional)**, enter and confirm any nonempty
passphrase, then save. A single character such as `1` is accepted; a strong random
passphrase is recommended. GPG output is actually decrypted and verified before
publication. Passphrases never enter command-line arguments, environment or logs.

On the receiving **installed** Node: select `.json` or `.gpg`, enter a passphrase
only for an encrypted file, and choose **Review backup**. Review counts, privacy mode and exclusions,
confirm trust, then **Restore on next restart**. Active connections and the
current configuration are not changed immediately. A pending import can be
cancelled in the same dialog. Restart normally to apply it before networking.
The archive requires the same Bitcoin Core version and network on the target.

See [the latest UX notes](BACKUP-UX-20261106.md) for independent windows and concurrent exports.

## Included

- Time zone and automatic time preference. Never the old wall-clock timestamp.
- Keyboard layout/model/variant/options; supported display scale; saved mouse
  speed preferences (only matching input device names will use them).
- Persistent NetworkManager Wi-Fi and Ethernet profiles, including system-saved
  passwords, autoconnect, static IP and DNS settings. Adapter bindings, BSSIDs,
  MAC addresses and old per-user permissions are removed. Profiles merge by
  UUID; unrelated target profiles remain. Only root may read installed secrets.
- Managed Node privacy profile (clearnet/Tor/WireGuard), private-broadcast choice,
  and the saved **single-peer managed WireGuard** config, including its keys.
  Existing strict WireGuard validation rejects scripts/includes/unsafe fields.
- Supported Core numeric preferences: pruning, dbcache, validation threads,
  mempool size/expiry, connection limit and upload target. Supported native GUI
  preferences: coin control, PSBT controls, minimize/tray behavior, monospaced
  font preference and language. Opaque Qt values are not deserialized.

## Deliberately not a full OS image

This configuration category contains no wallets, keys/descriptors, PSBTs, blockchain databases, account password
hashes, OS accounts, disk encryption, fstab, storage UUIDs, machine ID, SSH host
keys, Bluetooth pairing keys, monitor positions or source datadir paths are
copied. The target keeps its own login password and data disk. Bluetooth
hardware must be paired on the receiving adapter. Keystore/agent-only or
unsaved Wi-Fi passwords cannot be fabricated: missing stored credentials are
reported. Enterprise certificate-based profiles, third-party VPN plug-ins,
PAC/dispatcher scripts and unsupported connections are explicitly counted as
omissions, not silently claimed migrated. Arbitrary bitcoin.conf commands and
hooks are not imported; only supported numeric preferences are transferred.

A restored static IP or WireGuard private key can conflict with the original
machine if both are used simultaneously. Retire the original network identity
or provision a separate VPN peer before operating both. Switching from a
pruned preference to full history can require downloading missing blocks.
Only restore a backup you trust; a file checksum is not source authentication.

## Safety and crash recovery

The file is semantic, strictly bounded JSON inside GPG, never an archive of
arbitrary filesystem paths. Schemas reject unknown fields, duplicate keys,
invalid types, path traversal and unsupported versions. Network files are parsed,
normalized and verified with libnm. All imported writes target fixed paths or
validated direct NetworkManager filenames. Symlinks/hardlinks and nonregular
configuration files fail closed. External files are opened with the logged-in
Node user's permissions, not root path-resolution privileges.

Plaintext export/decryption work stays in private root-owned 0700 tmpfs, and
operations refuse active swap. Python memory is not claimed securely erased.
Once explicitly approved, pending settings (which contain network secrets) are
stored **root-only, mode 0600** in `/var/lib/core-node-settings/`. This is local
configuration staging, not encrypted-at-rest disk protection. During boot a
root-only rollback journal preserves the previous configuration. A crash before
commit restores it before a retry; committed changes are retained. Pending and
rollback secret copies are removed after successful completion. Existing system
Wi-Fi/WireGuard files naturally remain root-readable local configuration.

`core-node-settings-restore.service` runs before NetworkManager, the Node privacy
policy and Core. Failed recovery blocks those services rather than enabling an
unintended network fallback. A separate one-shot service applies the automatic
clock preference once D-Bus is available. No old date/time is restored. The GUI
can show the last result and cancel a pending operation. Root helpers print only
bounded non-secret status; neither network keys nor payloads are logged.

## Acceptance scope

Unit tests exercise schemas, real libnm parsing, actual GnuPG round trips,
wrong passwords, tampering, path boundaries, UI confirmation and menu layout.
Root-only disposable filesystem tests exercise commit, rollback, interrupted
journal recovery, local identity and wallet/chain preservation. Native VM tests
use synthetic Wi-Fi/WireGuard credentials and exFAT virtual USB media, with no
physical user's credentials, disks, wallets or blockchain touched.
Physical cross-machine Wi-Fi association and VPN reachability require testing
on real adapters and a real VPN server; saved-profile loading alone is not a
claim of successful wireless association or tunnel handshake.

Watch-only wallets are handled separately by the [grouped backup workflow](BACKUP-AND-RESTORE.md), using native Core public-only exports.
