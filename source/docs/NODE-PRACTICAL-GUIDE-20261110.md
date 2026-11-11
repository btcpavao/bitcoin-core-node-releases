# Node practical guide and copy-only backups — 10 November 2026

Base: 7f6856d9091964cf52947e73e6eb50b3821ba329 (all-state Home centering).
Local-only change. No Vault sources, physical user data or public releases changed.

The 19-chapter Guide begins with the complete Node/Vault workflow, then covers
watch-only financial privacy and optional login, pruning capacity/units/rescans,
receiving, PSBT transfer and the four backup categories. Existing networking,
input settings, status, updates, storage and diagnostic topics are preserved.
Native Guide, static HTML and plain text are synchronized.

Backup export alone omits the destination read-back pass. Blockchain checksums
are calculated while copying, with Core stopped and source identity checked.
All source reads, full writes, flushes, cancellation and atomic publish remain.
Core stays stopped after a blockchain backup. Restores retain manifest checks,
destination verification, isolated Core database validation and transaction guards.

Portable settings/public-wallet export has no USB re-read, no immediate GPG
decrypt-and-compare and no outgoing collection probe in a second Core process.
Native Core public-only exports, type restrictions, size/path checks, optional
GPG encryption and atomic write completion remain. Restore preview/import still
authenticates and validates. Existing formats are retained. General Encrypt Files
still uses the default round-trip verification; only Backup and Restore opts out.

A saved confirmation is not a media read-back or recovery guarantee. Separate
copies and periodic restore tests remain necessary. Normal sync/fsync may still
take time on a slow drive; it is a write-completion stage, not verification.
