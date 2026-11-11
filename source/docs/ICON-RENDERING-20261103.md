# Node footer button icons — visual parity with Vault

Blue Restart and red Shutdown use the **exact** original elementary-Xfce SVG
sources shipped in Bitcoin Core Vault. Green Network uses the existing Node
SVG with a white network topology symbol.

The former ImageMagick PNG converter mishandled gradient and composition,
creating a black center and leaving a faint colored ring, while hiding the
network pictogram. The corrected PNGs use Debian librsvg2-bin
2.60.0+dfsg-1+deb13u1 to render those same original SVG sources at
192 × 192 pixels with transparent RGBA. Source SVG, copyright records
and notices are preserved. No new icon artwork was invented.

Reproduction, from the directory containing source SVGs:

    rsvg-convert -w 192 -h 192 network-status.svg -o network-status.png
    rsvg-convert -w 192 -h 192 system-reboot.svg -o system-reboot.png
    rsvg-convert -w 192 -h 192 system-shutdown.svg -o system-shutdown.png

Tests in tests/test_footer_icon_color.py verify Vault original SVG hashes,
RGBA transparency, solid saturated color, white Network glyph and actual
Qt pixmaps at 44, 48, and 64 pixels. The old empty-ring PNGs fail.

No changes to button handlers, Footer layout, Core, NetworkManager or
data. Physical ThinkPad T550 acceptance is pending.
