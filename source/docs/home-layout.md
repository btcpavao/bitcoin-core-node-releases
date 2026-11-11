# Home card visibility and vertical fit

Import Watch-Only Wallet stays available. The Watch-Only Wallets manager is
hidden until a private-key-disabled descriptor wallet exists. Inventory runs
in a separate worker; successful imports reveal the manager immediately.
Read-only import records keep known wallets discoverable while Core is stopped.
When Core responds, its inventory takes precedence over stale records. No
wallet is loaded or created by this Home check.

The Home grid measures its header, visible feedback, footer and available
height. It reduces card height first, then icon sizes and spacing, then uses
a compact text profile only if necessary. Every title and description remains
visible. Ten/eleven-card transitions and active Node synchronization fit
800x600, 1024x768, 1280x720, 1366x768 and 1920x1080 logical displays without a
vertical scrollbar. Very narrow/unsupported displays retain scrolling rather
than clipping controls. Native display density scaling is preserved.
