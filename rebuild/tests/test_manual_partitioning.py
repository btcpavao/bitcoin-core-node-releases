"""Unit checks for the opt-in Node installer layout recipe (no disks touched)."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


RECIPE = Path(__file__).resolve().parents[1] / "enable-manual-partitioning.py"
spec = importlib.util.spec_from_file_location("partition_recipe", RECIPE)
recipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recipe)

ORIGINAL = """efi:
  mountPoint: /boot/efi
  recommendedSize: 512MiB
  minimumSize: 512MiB
  label: EFI
userSwapChoices: [none]
initialSwapChoice: none
initialPartitioningChoice: none
allowManualPartitioning: false
defaultFileSystemType: ext4
availableFileSystemTypes: [ext4]
enableLuksAutomatedPartitioning: false
lvm:
  enable: false
requiredStorage: 32.0
partitionLayout:
  - name: core-node
    filesystem: ext4
    mountPoint: /
    size: 100%
    minSize: 28G
"""


class ManualPartitioningRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        self.path = self.source / recipe.PARTITION_RELATIVE_PATH
        self.path.parent.mkdir(parents=True)
        self.path.write_text(ORIGINAL, encoding="utf-8")

    def test_opt_in_and_small_existing_efi(self):
        recipe.configure(self.source)
        updated = self.path.read_text(encoding="utf-8")
        expected = ORIGINAL.replace(
            "minimumSize: 512MiB", "minimumSize: 128MiB"
        ).replace(
            "allowManualPartitioning: false",
            "# Advanced/manual mode is opt-in. Never preselect an erase operation.\n"
            "allowManualPartitioning: true"
        )
        self.assertEqual(updated, expected)
        self.assertIn("initialPartitioningChoice: none", updated)
        self.assertIn("recommendedSize: 512MiB", updated)
        self.assertIn("partitionLayout:", updated)

    def test_fails_closed_on_erase_preselection(self):
        modified = ORIGINAL.replace("initialPartitioningChoice: none",
                                    "initialPartitioningChoice: erase")
        self.path.write_text(modified, encoding="utf-8")
        with self.assertRaises(ValueError):
            recipe.configure(self.source)
        self.assertEqual(self.path.read_text(encoding="utf-8"), modified)

    def test_fails_closed_on_efi_layout_change(self):
        modified = ORIGINAL.replace("minimumSize: 512MiB", "minimumSize: 64MiB")
        self.path.write_text(modified, encoding="utf-8")
        with self.assertRaises(ValueError):
            recipe.configure(self.source)
        self.assertEqual(self.path.read_text(encoding="utf-8"), modified)

    def test_fails_closed_on_missing_config(self):
        self.path.unlink()
        with self.assertRaises(ValueError):
            recipe.configure(self.source)

    def test_fails_closed_on_symlink(self):
        target = self.source / "other.conf"
        target.write_text(ORIGINAL, encoding="utf-8")
        self.path.unlink()
        self.path.symlink_to(target)
        with self.assertRaises(ValueError):
            recipe.configure(self.source)
        self.assertEqual(target.read_text(encoding="utf-8"), ORIGINAL)


if __name__ == "__main__":
    unittest.main()
