#!/usr/bin/env python3
"""Fail-closed, minimal extension of the pinned Node installer partition choices.

Runs after the authenticated RC2 source and the published RC3 patch are applied.
No disk or firmware is touched here: this changes the installer configuration in
a disposable source tree that will later become a *candidate* ISO.
"""
from pathlib import Path
import sys


PARTITION_RELATIVE_PATH = Path("runtime/etc/calamares/modules/partition.conf")

REQUIRED_LINES = (
    "minimumSize: 512MiB\n",
    "allowManualPartitioning: false\n",
    "initialPartitioningChoice: none\n",
    "defaultFileSystemType: ext4\n",
    "availableFileSystemTypes: [ext4]\n",
    "enableLuksAutomatedPartitioning: false\n",
    "requiredStorage: 32.0\n",
)


def configure(source: Path) -> Path:
    partition_config = source / PARTITION_RELATIVE_PATH
    if partition_config.is_symlink() or not partition_config.is_file():
        raise ValueError("Expected a regular Node Calamares partition.conf")
    original = partition_config.read_text(encoding="utf-8")
    for line in REQUIRED_LINES:
        if original.count(line) != 1:
            raise ValueError(f"Unexpected installer configuration: {line.strip()}")
    if "mountPoint: /boot/efi\n" not in original:
        raise ValueError("EFI mount point changed; requires manual review")

    updated = original.replace(
        "minimumSize: 512MiB\n", "minimumSize: 128MiB\n", 1
    ).replace(
        "allowManualPartitioning: false\n",
        "# Advanced/manual mode is opt-in. Never preselect an erase operation.\n"
        "allowManualPartitioning: true\n", 1
    )
    # The 512 MiB recommended size remains for *new* EFI partitions. A reused
    # Mac EFI partition can be smaller. This does NOT protect users from
    # explicitly formatting the wrong partition in Calamares.
    partition_config.write_text(updated, encoding="utf-8")
    return partition_config


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: enable-manual-partitioning.py SOURCE_TREE", file=sys.stderr)
        return 2
    try:
        config = configure(Path(argv[1]))
    except (OSError, ValueError) as exc:
        print(f"Refusing to change Node installer: {exc}", file=sys.stderr)
        return 1
    print(f"Manual partitioning enabled in candidate: {config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
