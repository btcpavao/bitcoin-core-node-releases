# Local blockchain backup and import

Home footer (current): Bottom right shows Bitcoin Core connection status above date/time, followed by Network, Restart and Shutdown. Powered by Debian GNU/Linux remains centered.

Settings has Backup Chain State and Import Chain State. Output is an uncompressed directory with a versioned manifest, per-file SHA256 digests, Core version, network and pruning preference. In v2, an optional tip observed by RPC **before** shutdown is only a display hint: Core can finish flushing additional blocks. The exact tip is obtained by offline Core validation on the staged import. V1 backups with an exact tip remain supported. Fixed exported roots are blocks (including index and xor.dat), chainstate, optional chainstate_snapshot and indexes. Wallets, cookies, settings and network/login credentials are excluded. Same-version Node-produced backups only; raw Core folders and UTXO snapshots are not accepted.

The existing polkit helper serializes operations, stops the service cleanly, checks Core directory locks, and restores prior running/stopped state. Backups never reopen the live/source databases in a second Core process: they copy the fully stopped, locked data and verify every file. Import-only private namespace validation uses pinned upstream bitcoind with a bounded cache, no physical/virtual network interface, wallet disabled, no persistent mempool and disabled settings. All external file opens/mkdir/rename/delete operations use the authenticated desktop identity, no-follow directory descriptors and exclusive file creation. Links, special files, nested mounts, traversal, incomplete inventories, wrong networks/versions, checksum failures, volatile destinations and insufficient disk space are refused. Copying is streaming and cancellable with read-back verification and fsync. Shutdown/sleep are inhibited during the operation.

Imports stage on the installed data filesystem, validate with isolated Core, compare height/hash for legacy v1 or derive the exact tip for v2, acquire the Core lock, and journal the directory swap and prune preference. Recovery before every service start rolls an uncommitted activation back, or keeps a fully committed activation. Existing wallet files and unrelated preferences are never replaced. Orphan staging directories are cleaned only by the fixed root start preflight while the chain-operation lock is free.

A pruned copy preserves retained history, not already deleted blocks. Wallet rescans can need missing history. A checksum is not third-party data authentication; the dialog requires the user to confirm a trusted backup.

## Choosing a USB stick or external SSD

On the installed Node, open **Settings → Backup Chain State** and choose
**USB / External Drive…**. The drive picker lists USB-backed partitions with
supported persistent filesystems, including USB flash sticks and USB SSDs.
It does not show the internal installation disk, boot partitions, optical media,
Private Workspace or bare/unformatted USB devices.

- If the USB is mounted in Files, its mountpoint and available capacity appear
  in the picker. Choose **Use USB drive** to save directly to its root folder or
  **Choose folder on USB…** to select an existing subfolder.
- If it is detected but not mounted, selecting it invokes the normal
  **udisksctl** local-user mount operation. It is never formatted and no raw
  USB writes are performed by the picker. After the verified mount is detected,
  the requested folder choice continues automatically.
- **Choose folder…** still offers normal folders, but also has direct Qt
  sidebar shortcuts for every mounted USB partition. This avoids relying on
  the native Thunar/GVfs places panel, which the Qt folder dialog did not show.
- Import accepts the USB root or the exact **bitcoin-chain-…** folder. A relative
  latest-backup shortcut is published atomically only after the new backup is
  complete. Incomplete copies are never selected. Older snapshots are kept,
  not overwritten; sufficient space for another complete snapshot is required.
  Without a shortcut, completed legacy backup folders are detected automatically. Read-only USB
  drives are acceptable for import, while backup requires a writable USB.
- The root chain-backup helper accepts persistent USB filesystems under
  `/media/node` and verified block-backed UDisks2 mounts under
  `/run/media/node`. All other `/run` directories, RAM workspaces, system
  paths and Bitcoin Core's own datadir remain forbidden destinations.

**Before stopping Core**, the helper now checks that the selected directory
exists and can be opened as the normal logged-in Node user, that it is
persistent rather than RAM-only, and that it is writable for backup. A missing
or unplugged external disk therefore does **not** interrupt sync. After
stopping Core, it checks the exact required capacity and FAT32 file-size
limits, streams a verified copy, and checks every file before atomically
publishing the finished backup folder. No wallet databases are included.

The local test suite covers USB SSDs and sticks, manually unmounted drives,
mountpoint filtering and read-only import, plus a synthetic full
block/index/chainstate copy and SHA256 manifest readback. Physical T550 tests
with an actual ext4/exFAT/NTFS external disk remain required.

Physical T550 acceptance remains a user test. Exact ISO acceptance records live beside the local build artifacts.

Native acceptance refinements: explicit footer sizing releases the wide X11 minimum before shrinking; QProcess completion uses operation_finished rather than the inherited QDialog finished signal; pruning updates use the shared managed DATA/settings.json on every network. tests/chain_process_ui.py covers completion, cancellation, non-cancellable commit and process startup failure with real child processes.

An import before the first Core launch also commits a root-owned, bounded import receipt. Startup then supplies the managed datadir explicitly, skipping upstream Intro before it can overwrite imported pruning. Fresh installations without an import retain the normal Intro. The receipt is published by committed-journal recovery, so interrupted imports retain the prior first-start decision. No user GUI preferences are overwritten.

## 6 November 2026 — cold-copy backup and drive-root import

The backup no longer runs a second Core over the source before copying. This removes the unnecessary source database reopen / validation failure path and its immediate recovery restart. A failure or cancellation reports whether the original Core was restarted. Imports retain isolated validation and now return bounded Core startup diagnostics instead of hiding the reason behind one generic message. No validation checks on the imported database are bypassed.

This is a complete snapshot, not an in-place incremental update: previous successful snapshots survive a failed new copy. Files are never published as a successful backup until copy, checksum readback and flush complete. The root shortcut selects the most recently completed snapshot. Wallets and network/login credentials are not exported. Pruned data includes only retained blocks, not previously deleted history.

Repeated deliberate maintenance restarts clear only this unit's systemd failed/start-rate counter after a verified clean stop. Automatic service restart remains disabled; this does not turn crashes into an automatic restart loop.

### Existing installations: do not reinstall to obtain this fix

The normal Node installer erases its selected disk. To preserve an already
synchronized chain, use the accompanying offline four-file update bundle on the
**installed Node**, not on the build workstation. Verify its supplied checksum,
extract it, then run `sudo python3 install.py --check` and `sudo python3 install.py`
from the bundle folder. Restart normally afterwards to reload open GUI modules.
The updater checks the exact known 5 November hardware-image file hashes (or
already-installed replacement hashes), serializes against the Node admin and
software-update locks, saves prior application files, and atomically replaces
only `chain_backup.py`, `chain_probe.py`, `chain_ui.py` and `usb_dialog.py`.
It refuses unknown revisions and does not read or change chain data, wallets,
login credentials or network settings. The bundle is a local development
artifact, not a signed public release.

Both computers should run the fix when transferring a new v2 backup. New code
still accepts v1 backups; older code does not understand v2 or the latest-backup
shortcut. Backup verification establishes copied-byte integrity, not trust in an
unknown third party's blockchain state. Use copies from your own trusted node.
