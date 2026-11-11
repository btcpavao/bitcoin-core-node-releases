# Guide, technical details, USB pickers and update-source resilience

Base runtime: `e3843cdcbb78cfcb21906899f7030723238a56d3` (Backup UX ISO).

## Reproduced update error

On 8 November 2026 the existing `keepass_updates.latest_release()` reproduced
"The official KeePassXC server could not be reached. Check the connection and
system clock, then try again." The underlying response on the development
ThinkCentre was **HTTP 503 Service Unavailable** from
`https://api.github.com/repos/keepassxreboot/keepassxc/releases/latest`.
The exact cause on the physical T550 is not established without its log.
At the same time, `https://keepassxc.org/download/` returned HTTP 200 and exact
stable 2.8.0 x86-64 AppImage and detached-signature links.

## Fix and trust boundaries

Transient HTTP/network failures receive one bounded retry. Rate limits and long
Retry-After instructions are not hammered. When the GitHub discovery endpoint
is unavailable, the official KeePassXC download page may identify exactly one
stable x86-64 release with a matching `.sig` link. A requested explicit version
is never replaced by a different one. Invalid metadata, certificate failures,
unknown redirect hosts and insecure URLs are not bypassed.

HTTP, DNS, timeout, TLS and local save failures now have separate messages.
The UI shows the release source and fallback note. If the complete check fails,
Debian findings remain visible but installation stays disabled until a fresh
complete check succeeds. An older record cannot trigger a downgrade or a false
up-to-date result. The existing pinned-key GPG verification still runs before
an AppImage can be extracted or activated. No GitHub token, unofficial mirror,
TLS bypass or signature bypass is introduced.

Primary upstream references:
- https://keepassxc.org/download/
- https://keepassxc.org/verifying-signatures/
- https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api

## Desktop changes

- Show technical details opens an independent, resizable/minimizable window.
  Grouped fields, search, expand/collapse, explicit snapshot refresh, copy and a
  separate raw-JSON tab replace the small inline scroll area. No telemetry;
  users are warned about private information before sharing a snapshot.
- Node Guide has 15 illustrated chapters, current backup/restore button labels,
  all four backup categories, optional encryption, configuration staging on
  restart, manual Core start after chain backup, parallel-operation limits,
  watch-only collection limitations and RAM-only PSBT behavior. Its HTML and
  plain-text copies are synchronized with the native text. Icons are bundled
  existing assets; diagrams use the existing local measured renderer.
- Encrypt Files/Decrypt Files input and encrypted-destination selectors show
  Places and hot-plug USB media in a left-hand pane. Unmounted supported media
  mounts only after explicit selection and identity recheck via UDisks.
  Read-only input is allowed; read-only output is refused. Decryption still
  recovers only into Private Workspace, not directly onto USB.
- Thunar's sidebar default is at least 280 logical pixels, preserving an already
  wider setting. Existing sessions pick this up at next normal desktop login.

## Verification scope

Offline tests cover transport failure classes, stable/version/host/signature-link
validation, blocked incomplete installs, independent-window lifecycle, media
revalidation/read-only state, guide completeness and sidebar width. Layouts are
rendered at supported sizes. Exact-image/native acceptance is recorded separately
in the build's ACCEPTANCE.json. Physical T550/USB tests are still required.
