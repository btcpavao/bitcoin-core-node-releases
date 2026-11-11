# Vault-derived Node installer and desktop

The reference is Bitcoin Core Vault commit `110f8ccd651408145de6ec4acd6a1ad70b84309c`. `VAULT-ORIGIN.json` records the exact source files and hashes.

The Calamares source patch is carried over unchanged under `calamares/vault/`. `patch_node.py` adapts product names, asset/helper paths and the Review explanation for persistent storage and networking. It retains the actual Vault header, three-step indicator, keyboard and disk controls, acknowledgement, progress view, finish view and navigation geometry. Debian Calamares 3.3.14-1 is required. The ISO build compiles the modified package in its disposable Debian builder and retains corresponding source and checksums in the artifact.

Disk eligibility and identity revalidation come from Vault. Node raises the minimum to 32 GiB. Only one eligible internal whole disk can be selected; mounted disks, the installation USB, missing identities and changed devices are rejected before partition jobs. The underlying partition engine and Node target setup remain in use.

The desktop widgets in `app/desktop_surface.py`, taskbar, Home helper, Num Lock helper and Openbox theme/rules also come from Vault. Node supplies its own existing actions and ordinary restart/shutdown confirmation. The live installer has a separate session and an explicit restart completion action. Closing or failing the installer opens the Vault-style diagnostic/retry flow instead of an empty desktop.

Node retains disk-backed user/data directories, firewall profiles, network services, bounded administration, manual native Bitcoin Core startup and wallet workflows. No Vault RAM mounts, storage checks, countdowns or memory-loss notices are included. Network connections are available in Node Settings.

Calamares and these carried-over source modifications retain GPL-3.0-or-later terms and upstream notices. Bitcoin/Debian artwork attribution is retained in the project asset notices.


## Password-free installation

The installer offers keyboard layout, disk selection and review. Automated LUKS
partitioning is disabled; neither a disk password nor a login password is offered.
After installation the desktop opens automatically. Settings > Login Password
lets the user set, change or remove the optional desktop login password.
Existing encrypted installations keep their independent disk-unlock setup.

## Native login screen

`build-greeter.sh` compiles Debian lightdm-gtk-greeter 2.0.9-1 with the small
`greeter/patch_greeter.py` presentation patch. LightDM and its existing PAM
conversation authenticate the fixed `node` account and start `core-node`.
The screen uses the shipped Bitcoin logo, product title, password entry and
Enter submission. User and session selection are not exposed. No custom
password verification, password storage or root UI process is introduced.

The patched Debian package and corresponding GPL source are retained together.
The greeter package is held, like the patched Calamares package; a new upstream
version must be rebuilt with the patch and validated before replacing it.
Acceptance covers wrong and correct passwords, retry, long input, automatic
login, removal, restart, keyboard navigation and the actual installed screen.
