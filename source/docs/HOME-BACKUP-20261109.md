# Home backup discovery — 9 November 2026

Base: login-only and successful-decryption workspace fixes (af477e0).

Home adds Backup and Restore immediately after Private Workspace, before Encrypt
Files. It opens the existing modeless hub, reusing its current window/jobs.
Settings always retains its own Backup and Restore entry.

A fresh install records a one-time, non-secret file-metadata fingerprint after target
defaults and installer choices. Merely opening Settings, automatic window sizing,
clock ticks, empty pointer state or an unused automatic Ethernet profile does not
reveal the card. Saved Wi-Fi/VPN, used Ethernet, paired Bluetooth, persistent time,
keyboard, display, mouse/login/privacy changes, Core activity or existing chain /
wallet entries do. Successful managed mutations also notify navigation state.

Detection runs in the existing Home health worker, with bounded read-only local
calls. No new privileged service, wallet opening, secret retrieval, credential
logs, network download, or automatic backup. It never reads wallet databases.
A private desktop-owned boolean at .local/state/bitcoin-core-node/home-backup.json
keeps the card visible after disconnect, Core stop, restart or backup creation.
A write failure does not block the desktop. Prior installations lacking a factory
baseline reveal the card conservatively, rather than classifying current settings
as factory defaults. This flag is not backup freshness or recoverability evidence.

The original backup categories and their exclusions remain unchanged: showing
this shortcut does not mean the login password or Bluetooth pairings are copied.
Thirteen visible cards retain five columns and Node Guide centered in the final
row. The login-only and decrypt-to-Private-Workspace changes remain included.

## Exact-image permission regression

Fresh-install testing exposed two incorrect assumptions: the root-created
LightDM preference is deliberately 0600, and Debian may create the user's
.local directory as 0775 for its own primary group. The desktop now compares
size/modification metadata for fixed OS preferences rather than reading their
contents. The one-way user flag accepts the user's own group-writable parent,
but still refuses world-writable or foreign-owned/group-writable paths. No
system or existing directory permissions are modified. Baseline format is 2.
Regression tests reproduce both conditions and preserve private OS file modes.
