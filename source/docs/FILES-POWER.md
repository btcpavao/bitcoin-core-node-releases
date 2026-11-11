# Core files and conditional shutdown

Files opens Core data through a read-only bindfs view at `/run/core-node-files/Core`.
Core reads and writes its original persistent data directory directly. The view
changes neither source ownership nor source permissions. The Node desktop can
inspect files owned by the separate Core account without opening a root file
manager. Wallet changes and consistent backups stay in native Bitcoin Core.

Core and Private Workspace lead Thunar's sidebar. Other user bookmarks and normal
USB drives remain available. The places helper derives from Vault's
`core-vault-file-places`; the two confirmations and countdown derive from Vault's
`core-vault-finish` (MIT, Vault source commit
`51059c52372a7b149a800183963f5300a2f4ebb1`). Copy is scoped to the Node RAM
workspace: Core's saved blockchain and loaded wallets remain on disk.

An empty Private Workspace gets one ordinary power confirmation. Any entry,
including a hidden file, dangling link or empty subfolder, enables both warnings
and the five-minute monotonic countdown. Failure to verify the workspace takes
the warning path. A second check catches files created while the ordinary
confirmation was open. Cancel, Escape and window close preserve the session;
the immediate action explicitly skips the wait. No Core stop or power request
occurs before final acceptance. The existing privileged helper still waits for
Core's clean shutdown before asking systemd to restart or power off.

Validation covers occupancy, conditional routing, elapsed-time expiry, all
cancellation controls, duplicate requests, layouts at 800×600 and 1366×768,
read-only access through the installed view, live file visibility, native Thunar
places/default location and actual installed restart/shutdown behavior.
