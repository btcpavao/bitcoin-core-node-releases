#!/usr/bin/env python3
"""Verify the Debian hardware package set in an exact built Node ISO.

A package manifest proves inclusion only; it cannot certify any physical
device, firmware loading, driver bindings, network association, or Secure Boot.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

EXPECTED_FIRMWARE = {
    "bluez-firmware",
    "firmware-linux-free",
    "firmware-ath9k-htc",
    "firmware-carl9170",
    "firmware-iwlwifi",
    "firmware-realtek",
    "firmware-atheros",
    "firmware-brcm80211",
    "firmware-mediatek",
    "firmware-libertas",
    "firmware-ti-connectivity",
    "firmware-amd-graphics",
    "firmware-intel-graphics",
    "firmware-intel-misc",
    "firmware-nvidia-graphics",
    "firmware-misc-nonfree",
    "firmware-bnx2",
    "firmware-bnx2x",
    "firmware-cavium",
    "firmware-qlogic",
    "firmware-netxen",
    "firmware-netronome",
    "firmware-myricom",
    "firmware-zd1211",
    "intel-microcode",
    "amd64-microcode",
}
EXPECTED_DRIVERS_AND_DIAGNOSTICS = {
    "linux-image-amd64",
    "xserver-xorg",
    "xserver-xorg-input-libinput",
    "xserver-xorg-video-amdgpu",
    "xserver-xorg-video-nouveau",
    "libgl1-mesa-dri",
    "network-manager",
    "wpasupplicant",
    "bluez",
    "rfkill",
    "pciutils",
    "usbutils",
    "ethtool",
    "iw",
}
REQUIRED = EXPECTED_FIRMWARE | EXPECTED_DRIVERS_AND_DIAGNOSTICS


def parse_packages(data: str) -> set[str]:
    """Live-build filesystem.packages uses 'name[:arch] version' lines."""
    return {
        line.split()[0].split(":", 1)[0]
        for line in data.splitlines()
        if line.strip()
    }


def check_iso(iso: Path) -> None:
    if not iso.is_file():
        raise ValueError(f"Missing ISO: {iso}")
    with tempfile.TemporaryDirectory(prefix="core-node-iso-hardware-") as tmp:
        manifest = Path(tmp) / "filesystem.packages"
        subprocess.run(
            [
                "xorriso", "-osirrox", "on", "-indev", str(iso),
                "-extract", "/live/filesystem.packages", str(manifest),
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        present = parse_packages(manifest.read_text())
    missing = sorted(REQUIRED - present)
    if missing:
        raise ValueError("ISO missing expected hardware packages: " + ", ".join(missing))
    # Neither the kernel module nor its broad blacklists are safe to include
    # generically without a device-selective policy and hardware regression test.
    forbidden = sorted(present & {"broadcom-sta-dkms", "r8168-dkms"})
    if forbidden:
        raise ValueError("Unreviewed global driver conflicts: " + ", ".join(forbidden))
    print(f"PASS: {len(REQUIRED)} hardware/firmware packages in {iso.name}")
    print("Scope: installed package manifest only; no physical hardware acceptance")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", required=True, type=Path)
    args = parser.parse_args()
    try:
        check_iso(args.iso)
    except (ValueError, subprocess.CalledProcessError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
