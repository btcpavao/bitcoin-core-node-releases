# Adaptive display size

Node and Vault share the same core-display-scale session helper. Video modes are
left unchanged: the X server retains the monitor's selected native mode.

At login, choose the primary active output, otherwise an internal eDP/LVDS/DSI
panel, otherwise the first active output. Validate its physical dimensions,
calculate density and round scaling to 25% steps (100–300%). Typical 15.6-inch
1366x768, 1600x900, 1920x1080 and 3840x2160 panels select 100%, 125%, 150% and
300%. An internal panel with missing physical dimensions uses its resolution
relative to 1366x768. An unknown external monitor defaults to 100%.
Cap scaling so each active output retains at least 800x600 logical pixels.

Xft.dpi is shared with Qt, GTK text and Openbox. Qt uses fractional scaling;
GTK3 uses integer widget scaling and density-adjusted text. GTK3's fractional
icon geometry can differ from Qt; this is an X11/GTK3 limitation.

The X11 session uses one shared scale, following the primary output. Mixed-DPI
monitors cannot each get independent scaling here. Detection runs at session
startup; reconnecting a different display requires signing out/restarting.
No resolution-changing xrandr calls or framebuffer stretching are used.

For a manual preference, set /etc/core-display-scale.conf to auto or a number
such as 1.25 or 1.5 and restart the session. The live and installed sessions
both read this setting. Vault's volatile home and wallet policies are unchanged.

Diagnostics (read-only):
    core-display-scale --diagnose
    cat "$XDG_RUNTIME_DIR/core-display-scale.json"

Qt: https://doc.qt.io/qt-6/highdpi.html
GTK3: https://docs.gtk.org/gtk3/x11.html
