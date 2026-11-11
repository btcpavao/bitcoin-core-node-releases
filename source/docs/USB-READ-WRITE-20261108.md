# Removable-media read/write and sidebar policy

Based on Guide/USB/Updates commit d5cc3b3; includes the restore-picker change
0e835fc and the completed all-application audit.

All Node-created file and directory pickers use MediaFileDialog: chain backup
and restore, Node/Core settings backup and restore, watch-only collections,
file encrypt/decrypt inputs and encrypted outputs, and managed WireGuard input.
Native Qt preferences are initialized for both the desktop and the separate
Core account; GTK uses its live volume monitor. KeePassXC's RAM config receives
the same policy. Thunar defaults to 320 logical pixels, custom/Qt pickers to
320 or more when labels need it, GTK Places to 300. Wider saved choices remain.

Core's official executable is unchanged. A fixed root-managed bindfs service
exposes only verified currently mounted external filesystems under
/run/core-node-media. Its writable sandbox adds only that root, not /media,
/run or /. Exports are created for node:node with owner read/write; existing
file ownership and modes are not modified. Source device number, canonical
mountpoint, filesystem, inode, mount ID and read-only status are checked.
Each remount has a new identity/path. Read-only media is never upgraded to rw.
The unmounted root is root-owned and each empty stub is non-writable. No disk
fallback, raw-device access, remote downloads or executable hooks are added.

No resolve-symlinks, forwarded device/ioctl or writable extended attributes
are enabled in the root helper. Core follows links only under its own existing
sandbox. All other existing ReadWritePaths and protection flags remain intact.
The threat model still trusts the local desktop/admin and inserted filesystem;
this is not protection against a malicious root/kernel or compromised firmware.

For safe removal finish writes and stop Core normally before ejecting in Files.
The service releases its pinned view when Core stops. It does not forcibly
unmount an in-use disk. Other desktop applications use their ordinary mount.
Qt's upstream file dialogs may need reopening after hot-plug; the persistent
USB Media entry provides access without restarting the application. Node-owned
pickers rescan while open. Supported encrypted devices are unlocked in Files.

Decryption remains RAM-only; copy recovered files through Files to persist them.
Core exports/PSBTs and KeePassXC/Editor files can be saved directly to USB.
A USB filesystem must itself be writable and have free space. Never declare a
save successful after a failed or unplugged-media write.

## Boot-order regression found during exact-image acceptance

The inherited RAM PSBT path watcher depended on core-node-private.service,
which (as a normal service) starts after basic.target. Default path dependencies
also ordered the watcher before paths.target and therefore before basic.target.
On a fresh UEFI boot, systemd dropped the RAM preparation job to break this
cycle, and LightDM could not start. The watcher now disables that implicit
path ordering, explicitly waits for basic/RAM preparation and retains its
shutdown ordering/conflict. This does not disable RAM verification or any
service protection. A regression test and fresh exact-image boots cover it.
