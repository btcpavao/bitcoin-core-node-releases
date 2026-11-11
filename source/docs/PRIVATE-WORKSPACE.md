# Node Private Workspace and native Core tools

Local development change requested 2026-10-29. Bitcoin Core remains the official pinned 32.1 binary. No GitHub publication is implied by this work.

Home removes Create Transaction, Import Signed PSBT and Wallet Backup. Their dialogs, custom PSBT proposal persistence/broadcast backend and privileged wallet-snapshot action are removed. Watch-Only Wallets retains balances, history and receiving addresses. Core itself handles PSBTs and consistent wallet databases.

Private Workspace lives at `/run/core-node-private/workspace`, inside a dedicated bounded tmpfs with `noswap,nodev,nosuid,noexec`. Both the desktop and the existing unprivileged Core service can use it. No other users have access. Separate mode-0700 RAM directories hold GPG staging, Qt settings and scratch files. Completed authenticated recovery is published to a new directory without overwriting existing files. GPG passphrases use anonymous pipes; no subprocess transcript contains secrets.

Swap and hibernation are disabled, disk core dumps are disabled, and the desktop requires successful private mount/preparation. Encryption/decryption and the workspace launcher check the actual mount, flags, ownership, permissions and inactive swap, with no persistent fallback. Thunar thumbnails/recent-file recording are disabled and desktop scratch/cache use RAM. A normal suspend retains RAM. Restart/shutdown/power loss lose workspace files. This does not promise physical RAM sanitization or protection against a compromised running OS.

Core blockchain, active wallet databases, network/login settings, ordinary home files and Public Wallet Transfer remain persistent. Copying plaintext to those locations, or restoring it into Core, creates a persistent copy. Back up an active wallet with Core File → Backup Wallet into Private Workspace; Encrypt Files processes that closed snapshot. Save encrypted output to USB/disk before leaving the session. Decrypt Files never offers a persistent plaintext destination.

The generic GnuPG backend and layered TAR recovery derive from the tested Vault source at commit `51059c52372a7b149a800183963f5300a2f4ebb1`, `tools/core-vault/backup-src/src`. GnuPG handles cryptography; no wallet/PSBT parser is added. New encrypted files use AES-256 OCB. Explicit ordinary single-layer recovery also accepts authenticated AES-256 MDC. Layered Node/Vault GPG files interoperate. The MIT notice is bundled with the installed code.

Validation must include real GPG corruption/cancellation/no-overwrite tests, native Core database round trips, layout checks, both installer modes, and exact-ISO installed checks. Installed checks must verify: no swap/hibernation, mount flags, ordinary desktop/Core access, wrong-password/tampered output rejection, no plaintext on the installed disk, workspace disappearance after reboot and cold power cycle, and persistence of independent Core data. Physical T550 acceptance follows VM acceptance. Prior image reports retain their original scope.

Kernel tmpfs reference: https://docs.kernel.org/filesystems/tmpfs.html
GnuPG status/options reference: https://www.gnupg.org/documentation/manuals/gnupg/GPG-Esoteric-Options.html
