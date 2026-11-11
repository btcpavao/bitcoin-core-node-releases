# USB sidebar for every Backup and Restore chooser

Built on the Guide/USB/Updates source d5cc3b3. The previous Node, Core and
watch-only restore actions still opened the plain Qt file picker. They now
share the same Places and live USB / External media picker as Encrypt/Decrypt.

The shared picker also supports directory mode, so blockchain Restore can
choose the USB root or a complete backup subfolder. Backup destination folders
use that same sidebar with writable-media checks. Existing USB / External
Drive and Use latest backup controls remain available.

Only explicit selection mounts a revalidated filesystem with UDisks. Merely
opening the dialog does not mount drives, inspect backup contents, or start
restoration. Hot-plug refresh, identity checks, read-only restore support,
file-extension filters, review/confirmation and backend validations remain.
Removed media cannot become a completed folder selection. The old static
mounted-drive list is no longer used as authority for folder choosers.

No change to backup formats, encryption defaults, Core/wallet operations,
service restarts, RAM recovery policy or user network configuration.
Tests cover every category and directory/file policies independently.
Physical user USB acceptance must be distinguished from disposable VM tests.
