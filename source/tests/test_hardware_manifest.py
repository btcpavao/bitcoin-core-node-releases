"""Source-level guarantees for generic Node hardware firmware coverage."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from check_iso_hardware import REQUIRED, parse_packages


class HardwareManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / "packages.list").read_text()
        cls.packages = [
            item for line in cls.raw.splitlines()
            if (item := line.strip()) and not item.startswith("#")
        ]

    def test_all_expected_packages_requested(self):
        self.assertFalse(REQUIRED - set(self.packages), sorted(REQUIRED - set(self.packages)))

    def test_no_duplicate_packages(self):
        self.assertEqual(len(self.packages), len(set(self.packages)))

    def test_no_globally_conflicting_dkms_driver(self):
        self.assertNotIn("broadcom-sta-dkms", self.packages)
        self.assertNotIn("r8168-dkms", self.packages)
        self.assertNotIn("firmware-ipw2x00", self.packages)

    def test_apt_keeps_non_free_firmware(self):
        sources = (
            ROOT / "runtime/etc/apt/sources.list.d/core-node.sources"
        ).read_text()
        self.assertEqual(sources.count("Components: main non-free-firmware"), 2)

    def test_iso_manifest_check_is_build_gate(self):
        build = (ROOT / "build-iso.sh").read_text()
        self.assertIn(
            'python3 "$NODE_SOURCE/tests/check_iso_hardware.py" --iso live-image-amd64.hybrid.iso',
            build,
        )

    def test_manifest_parser(self):
        self.assertEqual(
            parse_packages("firmware-iwlwifi 1.0\nlibgl1-mesa-dri:amd64 2.0\n"),
            {"firmware-iwlwifi", "libgl1-mesa-dri"},
        )


if __name__ == "__main__":
    unittest.main()
